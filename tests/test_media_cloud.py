"""Native cloud adapters, safe downloads, and resumable local jobs (offline)."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from PIL import Image, PngImagePlugin

from app.api import generation_v2, media_providers as api, outputs
from app.core import database as db, llm, media_downloads as downloads, media_jobs as jobs, media_provider_config as config
from app.core.media_cloud import XAIAdapter, RunwayAdapter, FalAdapter, handle
from app.core.media_providers import MODELS, MediaRequest, ProviderError, model_for, validate_api_tool
from app.core.public_config import build_public_config


def png(size=(320, 320)):
    buffer = BytesIO(); metadata = PngImagePlugin.PngInfo(); metadata.add_text('prompt', 'private metadata')
    Image.new('RGB', size, 'orange').save(buffer, 'PNG', pnginfo=metadata)
    return buffer.getvalue()


VIDEO = b'\x00\x00\x00\x10ftypisom\x00\x00\x00\x00'


def semantic(provider, model_id, *, reference=False):
    model = model_for(provider, model_id)
    return MediaRequest(model.id, 'An orange', 'source' if model.source_aspect or (model.reference_aspect and reference) else model.ratios[0], model.resolutions[0],
                        model.durations[0] if model.durations else None, [('ref.png', png(), 'image/png')] if reference else [])


def tool(provider, model_id, reference=False):
    model = model_for(provider, model_id); request = semantic(provider, model_id, reference=reference)
    return {'id': 'api-tool', 'name': 'Create media', 'provider': provider, 'model': model_id, 'outputType': model.output,
            'api': {'ratios': [request.aspect_ratio], 'resolutions': [request.resolution], 'defaultResolution': request.resolution,
                    'references': 1 if reference else 0, 'requireImage': reference,
                    **({'durations': list(model.durations), 'defaultDuration': request.duration} if model.durations else {})}}


class CloudAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_checks_never_generate_paid_media(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.url.host == 'api.x.ai': return httpx.Response(200, json={'data': [{'id': 'grok-imagine-image-2.0'}]})
            if req.url.path.endswith('/organization'): return httpx.Response(200, json={'tier': {}, 'creditBalance': 100})
            if req.url.path.endswith('/by-endpoint'): return httpx.Response(200, json={'items': []})
            return httpx.Response(200, json={'models': [{'endpoint_id': 'fal-ai/flux-2-pro'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            self.assertEqual(await XAIAdapter().test(client, 'private-key'), ['grok-imagine-image-2.0'])
            self.assertIn('gen4.5', await RunwayAdapter().test(client, 'private-key'))
            self.assertEqual(await FalAdapter().test(client, 'private-key'), ['fal-ai/flux-2-pro'])
        self.assertTrue(all(req.method == 'GET' for req in calls))
        self.assertEqual(calls[1].headers['x-runway-version'], '2024-11-06')
        self.assertEqual(calls[2].headers['authorization'], 'Key private-key')
        self.assertEqual(calls[2].url.params['limit'], '1')
        self.assertEqual(len(calls[3].url.params.get_list('endpoint_id')), len(MODELS['fal']))

    async def test_bad_credentials_and_catalogs_use_safe_errors(self):
        for adapter in (XAIAdapter(), RunwayAdapter(), FalAdapter()):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(401, text='private-key'))) as client:
                with self.assertRaises(ProviderError) as caught: await adapter.test(client, 'private-key')
                self.assertNotIn('private-key', str(caught.exception))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={}))) as client:
            for adapter in (XAIAdapter(), RunwayAdapter(), FalAdapter()):
                with self.assertRaises(ProviderError): await adapter.test(client, 'private-key')

    async def test_xai_image_generation_and_edit_contracts(self):
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}], 'usage': {'total_tokens': 4, 'cost': 1}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            for reference in (False, True):
                result = await XAIAdapter().submit(client, 'private-key', semantic('xai', 'grok-imagine-image-2.0', reference=reference))
        self.assertEqual([r.url.path for r in calls], ['/v1/images/generations', '/v1/images/edits'])
        body = json.loads(calls[1].content)
        self.assertEqual((body['resolution'], body['response_format']), ('1k', 'b64_json'))
        self.assertEqual(body['image']['type'], 'image_url')
        self.assertTrue(body['image']['url'].startswith('data:image/png;base64,'))
        self.assertEqual(result.media[0].data, png())
        self.assertEqual(result.usage, {'total_tokens': 4})

    async def test_xai_video_submission_pending_completion_and_download(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.method == 'POST': return httpx.Response(200, json={'request_id': 'video-job'})
            if req.url.host == 'vidgen.x.ai': return httpx.Response(200, content=VIDEO, headers={'content-type': 'video/mp4'})
            return httpx.Response(200, json={'status': 'pending'} if len(calls) == 2 else {'status': 'done', 'video': {'url': 'https://vidgen.x.ai/output.mp4', 'respect_moderation': True}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await XAIAdapter().submit(client, 'private-key', semantic('xai', 'grok-imagine-video-1.5', reference=True))
            self.assertEqual((await XAIAdapter().poll(client, 'private-key', result.remote_id)).remote_id, result.remote_id)
            final = await XAIAdapter().poll(client, 'private-key', result.remote_id)
        body = json.loads(calls[0].content)
        self.assertEqual(body['duration'], 5)
        self.assertNotIn('aspect_ratio', body)  # xAI preserves the input frame's aspect.
        self.assertTrue(body['image']['url'].startswith('data:'))
        self.assertNotIn('authorization', calls[-1].headers)
        self.assertEqual(final.media[0].data, VIDEO)

    async def test_runway_image_reference_and_video_request_shapes(self):
        calls = []
        def transport(req):
            calls.append(req); return httpx.Response(200, json={'id': 'task-id'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            for model_id, reference in [('gen4_image', False), ('gen4_image_turbo', True), ('gen4.5', False), ('gen4.5', True), ('gen4_turbo', True)]:
                await RunwayAdapter().submit(client, 'private-key', semantic('runway', model_id, reference=reference))
        self.assertEqual([r.url.path for r in calls], ['/v1/text_to_image', '/v1/text_to_image', '/v1/text_to_video', '/v1/image_to_video', '/v1/image_to_video'])
        bodies = [json.loads(req.content) for req in calls]
        self.assertEqual(bodies[0]['ratio'], '1024:1024')
        self.assertEqual(bodies[1]['referenceImages'][0]['tag'], 'reference1')
        self.assertEqual(bodies[2]['ratio'], '1280:720')
        self.assertTrue(bodies[3]['promptImage'].startswith('data:image/png;base64,'))
        self.assertTrue(all(req.headers['x-runway-version'] == '2024-11-06' for req in calls))

    async def test_provider_input_limits_fail_before_post(self):
        calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: calls.append(req))) as client:
            invalid = [semantic('runway', 'gen4_image_turbo'), semantic('runway', 'gen4_image'), semantic('fal', 'fal-ai/flux-2-pro/edit')]
            invalid[1].prompt = '😀' * 501
            for adapter, request in zip((RunwayAdapter(), RunwayAdapter(), FalAdapter()), invalid):
                with self.assertRaises(ProviderError): await adapter.submit(client, 'key', request)
            request = semantic('runway', 'gen4_image', reference=True)
            request.images[0] = ('big.png', b'x' * 3_750_001, 'image/png')
            with self.assertRaises(ProviderError): await RunwayAdapter().submit(client, 'key', request)
        self.assertEqual(calls, [])

    async def test_runway_polling_and_failure_messages(self):
        for state in ('PENDING', 'THROTTLED', 'RUNNING', 'FAILED', 'CANCELLED'):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={'status': state, 'failure': 'private-key'}))) as client:
                if state in {'FAILED', 'CANCELLED'}:
                    with self.assertRaises(ProviderError) as caught: await RunwayAdapter().poll(client, 'key', 'image:task-id')
                    self.assertNotIn('private-key', str(caught.exception))
                else:
                    self.assertEqual((await RunwayAdapter().poll(client, 'key', 'image:task-id')).remote_id, 'image:task-id')

    async def test_fal_generators_editors_and_kling_first_frame_contracts(self):
        calls = []
        def transport(req):
            calls.append(req); return httpx.Response(200, json={'request_id': 'request-id', 'status_url': 'https://evil.example/ignored'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            for model_id in ('fal-ai/flux-2-pro', 'fal-ai/flux-2-pro/edit', 'kling/v4/flash/text-to-video', 'kling/v4/flash/image-to-video'):
                model = model_for('fal', model_id)
                await FalAdapter().submit(client, 'key', semantic('fal', model_id, reference=model.requires_image))
        bodies = [json.loads(req.content) for req in calls]
        self.assertEqual(bodies[0]['image_size'], 'square_hd')
        self.assertEqual(bodies[1]['output_format'], 'png')
        self.assertTrue(bodies[1]['image_urls'][0].startswith('data:'))
        self.assertEqual(bodies[2]['aspect_ratio'], '16:9')
        self.assertTrue(bodies[3]['start_image_url'].startswith('data:'))
        self.assertNotIn('aspect_ratio', bodies[3])
        self.assertTrue(all(req.headers['x-fal-no-retry'] == '1' for req in calls))

    async def test_fal_polling_uses_app_path_and_ignores_response_urls(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.url.host == 'v3b.fal.media': return httpx.Response(200, content=png(), headers={'content-type': 'image/png'})
            if req.url.path.endswith('/status'): return httpx.Response(200, json={'status': 'COMPLETED', 'response_url': 'https://evil.example'})
            return httpx.Response(200, json={'images': [{'url': 'https://v3b.fal.media/result.png'}]})
        remote = json.dumps({'model': 'fal-ai/flux-2-pro/edit', 'id': 'request-id'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await FalAdapter().poll(client, 'private-key', remote)
        self.assertEqual([req.url.path for req in calls[:2]], ['/fal-ai/flux-2-pro/requests/request-id/status', '/fal-ai/flux-2-pro/requests/request-id'])
        self.assertEqual(result.media[0].data, png())
        self.assertNotIn('authorization', calls[-1].headers)

    async def test_invalid_remote_handles_never_make_requests(self):
        calls = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: calls.append(req))) as client:
            for adapter, remote in [(XAIAdapter(), 'video:../secret'), (RunwayAdapter(), 'https://evil.example'), (FalAdapter(), '{}'), (FalAdapter(), json.dumps({'model': 'evil/model', 'id': 'a'}))]:
                with self.assertRaises(ProviderError): await adapter.poll(client, 'key', remote)
        self.assertEqual(calls, [])

    async def test_source_aspect_tools_hide_format_and_require_references(self):
        for provider, model_id in [('fal', 'kling/v4/flash/image-to-video'), ('xai', 'grok-imagine-video-1.5')]:
            value = tool(provider, model_id, reference=True)
            validate_api_tool(value)
            public = build_public_config({'tools': [value]})['tools'][0]
            self.assertNotIn('width', public['nodeMapping'])
            self.assertEqual(public['aspectRatios'], {})
            self.assertTrue(public['nodeMapping']['image'])
            value['api']['requireImage'] = False
            with self.assertRaises(ValueError): validate_api_tool(value)


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_strips_credentials_cookies_and_checks_redirect_hosts(self):
        calls = []
        def transport(req):
            calls.append(req)
            if len(calls) == 1: return httpx.Response(302, headers={'location': 'https://v3b.fal.media/final.png'})
            return httpx.Response(200, content=png(), headers={'content-type': 'image/png'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport), headers={'Authorization': 'Key secret', 'X-API-Key': 'secret'}, cookies={'session': 'secret'}) as client:
            result = await downloads.download_media(client, 'fal', 'https://v3.fal.media/image.png', 'image')
        self.assertEqual(result.data, png())
        self.assertTrue(all('authorization' not in req.headers and 'cookie' not in req.headers and 'x-api-key' not in req.headers for req in calls))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={'location': 'https://127.0.0.1/private'}))) as client:
            with self.assertRaises(ProviderError): await downloads.download_media(client, 'fal', 'https://v3.fal.media/image.png', 'image')

    async def test_private_or_malformed_urls_are_rejected(self):
        for url in ('http://vidgen.x.ai/a', 'https://vidgen.x.ai.evil.example/a', 'https://127.0.0.1/a', 'https://vidgen.x.ai:444/a', 'https://secret@vidgen.x.ai/a', 'https://vidgen.x.ai/a#fragment', 'https://vidgen.x.ai/a\n'):
            with self.assertRaises(ProviderError): downloads.delivery_url('xai', url)

    async def test_download_limits_types_and_safe_get_retries(self):
        for headers, content in [({'content-length': '1000'}, b'a'), ({}, b'x' * 21), ({'content-type': 'text/html'}, b'<html>')]:
            with patch.object(downloads, 'MAX_DOWNLOAD_BYTES', 20):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, headers=headers, content=content))) as client:
                    with self.assertRaises(ProviderError): await downloads.download_media(client, 'xai', 'https://vidgen.x.ai/out.mp4', 'video')
        calls = []
        def transport(req):
            calls.append(req)
            if len(calls) == 1: raise httpx.ReadTimeout('signed-secret-url')
            return httpx.Response(200, content=VIDEO, headers={'content-type': 'video/mp4'})
        with patch('asyncio.sleep', new=AsyncMock()):
            async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                self.assertEqual((await downloads.download_media(client, 'xai', 'https://vidgen.x.ai/out.mp4', 'video')).data, VIDEO)
        self.assertEqual(len(calls), 2)


class CloudJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); root = Path(self.temp.name)
        self.patches = [patch.object(db, 'DB_PATH', str(root / 'db.sqlite')), patch.object(jobs, 'OUTPUT_DIR', root / 'media'),
                        patch.object(config, 'SETTINGS_PATH', root / 'providers.json'), patch.object(jobs, 'credential', return_value='private-key'),
                        patch.object(jobs, 'metadata_scrubbing_enabled', return_value=True)]
        for item in self.patches: item.start()
        db.init_db(); self.manager = jobs.MediaJobManager()

    async def asyncTearDown(self):
        await self.manager.stop()
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    async def test_retry_download_recovers_completed_runway_job_without_resubmitting(self):
        app = FastAPI()
        app.include_router(api.router)
        app.include_router(outputs.router)
        app.include_router(generation_v2.router)
        native = httpx.AsyncClient
        calls = []
        download_available = False

        def transport(request):
            calls.append(request)
            if request.method == 'POST':
                return httpx.Response(200, json={'id': 'paid-task'})
            if request.url.path == '/v1/tasks/paid-task':
                return httpx.Response(200, json={'status': 'SUCCEEDED', 'output': ['https://dnznrvs05pmza.cloudfront.net/file.png']})
            if not download_available:
                return httpx.Response(503)
            return httpx.Response(200, content=png(), headers={'content-type': 'image/png'})

        def factory(**kwargs):
            return native(transport=httpx.MockTransport(transport), **kwargs)

        value = tool('runway', 'gen4_image')
        with patch.object(generation_v2, 'get_tool_settings', return_value=value), patch.object(api, 'job_manager', self.manager), patch.object(config, 'ready', return_value=True), patch.object(jobs.httpx, 'AsyncClient', side_effect=factory), patch('asyncio.sleep', new=AsyncMock()):
            async with native(transport=httpx.ASGITransport(app=app), base_url='http://orange') as client:
                response = await client.post('/api/generate', data={'tool_id': value['id'], 'prompt': 'An orange'})
                job_id = response.json()['prompt_id']
                await self.manager.tasks[job_id]
                self.assertEqual(jobs.get_job(job_id)['status'], 'delivery_failed')
                self.assertEqual(db.get_generation_record(job_id)['status'], 'delivery_failed')
                connection = AsyncMock()
                connection.is_disconnected.return_value = False
                events = [json.loads(event) async for event in jobs.status_events(connection, job_id)]
                self.assertTrue(events[-1]['retry_delivery'])
                await self.manager.start()
                self.assertNotIn(job_id, self.manager.tasks)

                download_available = True
                retry_url = f'/api/jobs/{job_id}/retry-download'
                retry = await client.post(retry_url)
                self.assertEqual(retry.status_code, 202, retry.text)
                task = self.manager.tasks.get(job_id)
                if task:
                    await task
                self.assertEqual((await client.post(retry_url)).status_code, 409)
                output = await client.get('/api/output', params={'prompt_id': job_id, 'type': 'image'})
                self.assertEqual(output.status_code, 200)
                self.assertEqual(db.get_generation_record(job_id)['status'], 'completed')
        self.assertEqual(sum(request.method == 'POST' for request in calls), 1)

    async def test_http_generation_polling_local_outputs_and_history_for_all_three(self):
        app = FastAPI(); app.include_router(generation_v2.router); app.include_router(outputs.router)
        native = httpx.AsyncClient
        for provider, models in [('xai', ('grok-imagine-image-2.0', 'grok-imagine-video-1.5')), ('runway', ('gen4_image', 'gen4.5')), ('fal', ('fal-ai/flux-2-pro', 'kling/v4/flash/text-to-video'))]:
            for model_id in models:
                model = model_for(provider, model_id); value = tool(provider, model_id); calls = []
                delivery = {'xai': 'https://vidgen.x.ai/out.mp4', 'runway': 'https://dnznrvs05pmza.cloudfront.net/out', 'fal': 'https://v3.fal.media/out'}[provider]
                def transport(req):
                    calls.append(req)
                    if str(req.url) == delivery: return httpx.Response(200, content=VIDEO if model.output == 'video' else png(), headers={'content-type': 'video/mp4' if model.output == 'video' else 'image/png'})
                    if req.method == 'POST':
                        if provider == 'xai' and model.output == 'image': return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
                        return httpx.Response(200, json={'id' if provider == 'runway' else 'request_id': 'remote-job'})
                    if provider == 'xai': return httpx.Response(200, json={'status': 'done', 'video': {'url': delivery}})
                    if provider == 'runway': return httpx.Response(200, json={'status': 'SUCCEEDED', 'output': [delivery]})
                    if req.url.path.endswith('/status'): return httpx.Response(200, json={'status': 'COMPLETED'})
                    return httpx.Response(200, json={'video': {'url': delivery}} if model.output == 'video' else {'images': [{'url': delivery}]})
                def factory(**kwargs): return native(transport=httpx.MockTransport(transport), **kwargs)
                with patch.object(generation_v2, 'get_tool_settings', return_value=value), patch.object(api, 'job_manager', self.manager), patch.object(config, 'ready', return_value=True), patch.object(jobs.httpx, 'AsyncClient', side_effect=factory), patch('asyncio.sleep', new=AsyncMock()):
                    async with native(transport=httpx.ASGITransport(app=app), base_url='http://orange') as client:
                        response = await client.post('/api/generate', data={'tool_id': value['id'], 'prompt': 'An orange'})
                        self.assertEqual(response.status_code, 200, response.text)
                        identifier = response.json()['prompt_id']; await self.manager.tasks[identifier]
                        self.assertEqual(jobs.get_job(identifier)['status'], 'completed', jobs.get_job(identifier)['error'])
                        output = await client.get('/api/output', params={'prompt_id': identifier, 'type': model.output})
                        self.assertEqual(output.status_code, 200)
                        if model.output == 'image':
                            with Image.open(BytesIO(output.content)) as image: self.assertNotIn('prompt', image.info)
                        self.assertEqual(db.get_generation_record(identifier)['provider'], provider)
                self.assertEqual(sum(req.method == 'POST' for req in calls), 1)

    async def test_restart_resumes_new_provider_jobs_using_only_get(self):
        for provider, model_id, remote in [('xai', 'grok-imagine-video-1.5', 'video:remote-id'), ('runway', 'gen4_image', 'image:remote-id'), ('fal', 'fal-ai/flux-2-pro', json.dumps({'model': 'fal-ai/flux-2-pro', 'id': 'remote-id'}))]:
            with patch.object(self.manager, '_schedule'):
                identifier = self.manager.submit(provider, model_for(provider, model_id), 'api-tool', semantic(provider, model_id), 'ip')['prompt_id']
            jobs._update(identifier, 'processing', remote_id=remote)
            delivery = {'xai': 'https://vidgen.x.ai/out.mp4', 'runway': 'https://dnznrvs05pmza.cloudfront.net/out.png', 'fal': 'https://v3.fal.media/out.png'}[provider]
            calls = []
            def transport(req):
                calls.append(req)
                if str(req.url) == delivery: return httpx.Response(200, content=VIDEO if provider == 'xai' else png())
                if provider == 'xai': return httpx.Response(200, json={'status': 'done', 'video': {'url': delivery}})
                if provider == 'runway': return httpx.Response(200, json={'status': 'SUCCEEDED', 'output': [delivery]})
                return httpx.Response(200, json={'status': 'COMPLETED'} if req.url.path.endswith('/status') else {'images': [{'url': delivery}]})
            native = httpx.AsyncClient
            def factory(**kwargs): return native(transport=httpx.MockTransport(transport), **kwargs)
            with patch.object(jobs.httpx, 'AsyncClient', side_effect=factory), patch('asyncio.sleep', new=AsyncMock()):
                await self.manager.start(); await self.manager.tasks[identifier]
            self.assertEqual(jobs.get_job(identifier)['status'], 'completed')
            self.assertTrue(all(req.method == 'GET' for req in calls))


class CloudCredentialsTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_keys_use_environment_without_exposing_them(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'SETTINGS_PATH', Path(directory) / 'providers.json'), patch.object(config, '_vault', return_value=''), patch.dict(os.environ, {'XAI_API_KEY': 'xai-secret', 'RUNWAYML_API_SECRET': 'runway-secret', 'FAL_KEY': 'fal-secret'}, clear=True):
            for provider in ('xai', 'runway', 'fal'):
                self.assertEqual(config.credential(provider), provider + '-secret')
                record = next(item for item in config.public_settings() if item['id'] == provider)
                self.assertTrue(record['configured']); self.assertTrue(record['supportsMedia'])
                self.assertNotIn(provider + '-secret', json.dumps(record))

    async def test_xai_prompt_enhancement_uses_central_key_and_text_model_endpoint(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.method == 'POST': return httpx.Response(200, json={'choices': [{'message': {'content': 'Enhanced'}}]})
            return httpx.Response(200, json={'models': [{'id': 'grok-text', 'output_modalities': ['text']}, {'id': 'grok-image', 'output_modalities': ['image']}]})
        native = httpx.AsyncClient
        def factory(**kwargs): return native(transport=httpx.MockTransport(transport), **kwargs)
        with patch.object(config, 'credential', return_value='xai-secret'), patch.dict(os.environ, {'OPENAI_API_KEY': 'wrong-key'}), patch.object(llm.httpx, 'AsyncClient', side_effect=factory):
            self.assertEqual(await llm.list_llm_models('xai', 'https://wrong.example', 'stale'), ['grok-text'])
            self.assertEqual(await llm.call_llm('xai', 'https://wrong.example', 'stale', 'grok-text', 'Improve', 'An orange'), 'Enhanced')
        self.assertEqual([str(req.url) for req in calls], ['https://api.x.ai/v1/language-models', 'https://api.x.ai/v1/chat/completions'])
        self.assertTrue(all(req.headers['authorization'] == 'Bearer xai-secret' for req in calls))
