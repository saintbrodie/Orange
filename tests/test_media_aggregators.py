"""Provider contracts use recorded documentation shapes; no paid requests."""
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
from app.core import database as db, llm, media_jobs as jobs, media_provider_config as config
from app.core.media_aggregators import OpenRouterAdapter, VeniceAdapter
from app.core.media_providers import ADAPTERS, Model, ModelDiscovery, MediaRequest, ProviderError, model_for, validate_api_tool


def png(size=(256, 256)):
    buffer = BytesIO()
    metadata = PngImagePlugin.PngInfo(); metadata.add_text('prompt', 'private')
    Image.new('RGB', size, 'orange').save(buffer, 'PNG', pnginfo=metadata)
    return buffer.getvalue()


def image_record(model_id='bytedance-seed/seedream-4.5', **changes):
    return {'id': model_id, 'name': 'Seedream 4.5', 'architecture': {'input_modalities': ['text', 'image'], 'output_modalities': ['image']},
            'supported_parameters': {'aspect_ratio': {'type': 'enum', 'values': ['1:1', '3:4']}, 'resolution': {'type': 'enum', 'values': ['1K', '2K']}}, **changes}


def venice_record(model_id='qwen-image-3', kind='image', **constraints):
    return {'id': model_id, 'type': kind, 'model_spec': {'name': model_id, 'constraints': constraints}}


def curated(provider, model):
    return {'id': 'api-image', 'name': 'Create image', 'provider': provider, 'model': model.id, 'outputType': 'image',
            'api': {'ratios': list(model.ratios), 'resolutions': list(model.resolutions), 'defaultResolution': model.resolutions[0],
                    'references': model.references, 'requireImage': model.requires_image}}


class AggregatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = patch.object(config, 'SETTINGS_PATH', Path(self.temp.name) / 'providers.json')
        self.paths.start(); self.addCleanup(self.paths.stop)
        self.keys = patch.object(config, 'credential', return_value='private-key')
        self.keys.start(); self.addCleanup(self.keys.stop)

    def cache(self, provider, models):
        config.save_provider(provider, {'enabled': True})
        config.save_discovery(provider, [m.id for m in models], 'private-key', definitions=models)

    async def test_openrouter_checks_auth_before_public_catalog_and_filters_capabilities(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.url.path.endswith('/key'): return httpx.Response(200, json={'data': {'label': 'private-key'}})
            return httpx.Response(200, json={'data': [image_record(), image_record('vendor/vector-model'),
                image_record('../invalid'), image_record('vendor/text', architecture={'output_modalities': ['text']}),
                image_record('vendor/fixed', supported_parameters={}),
                image_record('vendor/unsupported', supported_parameters={'aspect_ratio': {'values': ['1:100']}})]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await OpenRouterAdapter().test(client, 'private-key')
        self.assertEqual([r.url.path for r in calls], ['/api/v1/key', '/api/v1/images/models'])
        self.assertTrue(all(r.method == 'GET' and r.headers['authorization'] == 'Bearer private-key' for r in calls))
        self.assertEqual([m.id for m in result.models], ['bytedance-seed/seedream-4.5', 'vendor/fixed'])
        self.assertEqual(result.models[0].ratios, ('1:1', '3:4'))
        self.assertFalse(result.models[1].send_ratio)
        self.assertEqual(result.models[1].resolutions, ('standard',))

    async def test_openrouter_rejected_key_never_reads_public_catalog_or_echoes_body(self):
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(401, text='private-key')
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with self.assertRaises(ProviderError) as caught: await OpenRouterAdapter().test(client, 'private-key')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('private-key', str(caught.exception))

    async def test_discovery_survives_reload_and_keeps_existing_tools_after_refresh(self):
        old = Model('vendor/old', 'Old', references=0)
        new = Model('vendor/new', 'New', references=1)
        self.cache('openrouter', [old])
        self.cache('openrouter', [new])
        self.assertEqual(model_for('openrouter', old.id).name, 'Old')
        self.assertEqual(model_for('openrouter', new.id).references, 1)
        record = next(p for p in config.public_settings() if p['id'] == 'openrouter')
        self.assertEqual(record['models'], [new.id])
        self.assertTrue(record['supportsMedia'])
        self.assertNotIn('private-key', config.SETTINGS_PATH.read_text())
        self.assertEqual(validate_api_tool(curated('openrouter', old)).id, old.id)

    async def test_route_caches_live_definitions_and_refuses_changed_credentials(self):
        model = Model('vendor/new', 'New', references=0)
        with patch.object(ADAPTERS['openrouter'], 'test', AsyncMock(return_value=ModelDiscovery([model]))):
            result = await api.test_provider('openrouter', _=True)
        self.assertEqual(result['models'], [{'id': model.id, 'name': model.name}])
        with self.assertRaises(ValueError): config.save_discovery('openrouter', [], 'old-key', definitions=[])
        self.assertEqual(config.settings()['openrouter']['discoveredModels'], [model.id])

    async def test_openrouter_generation_and_reference_shapes_and_usage_without_cost(self):
        model = Model('vendor/image', 'Image', ratios=('3:4',), resolutions=('2K',), references=1)
        self.cache('openrouter', [model])
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode(), 'media_type': 'image/png'}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 7, 'cost': .5, 'raw': 'private-key'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await OpenRouterAdapter().submit(client, 'private-key', MediaRequest(model.id, 'edit', '3:4', '2K', images=[('ref.png', png(), 'image/png')]))
        body = json.loads(calls[0].content)
        self.assertEqual(str(calls[0].url), 'https://openrouter.ai/api/v1/images')
        self.assertEqual((body['n'], body['aspect_ratio'], body['resolution']), (1, '3:4', '2K'))
        self.assertTrue(body['input_references'][0]['image_url']['url'].startswith('data:image/png;base64,'))
        self.assertEqual(result.usage, {'input_tokens': 3, 'output_tokens': 7})
        self.assertEqual(result.media[0].data, png())

    async def test_fixed_models_omit_unsupported_controls_and_vector_outputs_fail(self):
        model = Model('vendor/fixed', 'Fixed', ratios=('1:1',), references=0, send_ratio=False)
        self.cache('openrouter', [model])
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={'data': [{'b64_json': 'PHN2Zy8+', 'media_type': 'image/svg+xml'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            with self.assertRaises(ProviderError): await OpenRouterAdapter().submit(client, 'key', MediaRequest(model.id, 'draw', '1:1', 'standard'))
        self.assertEqual(set(json.loads(calls[0].content)), {'model', 'prompt', 'n'})

    async def test_venice_discovers_generators_and_required_image_editors(self):
        calls = []
        def transport(req):
            calls.append(req)
            data = [venice_record('z-image-turbo', promptCharacterLimit=1500)] if req.url.params['type'] == 'image' else [
                venice_record('qwen-image-3-edit', 'inpaint', aspectRatios=['1:1', '3:4'], resolutions=['1K', '2K']),
                venice_record('auto-only', 'inpaint', aspectRatios=['auto'])]
            return httpx.Response(200, json={'data': data})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await VeniceAdapter().test(client, 'private-key')
        self.assertEqual([r.url.params['type'] for r in calls], ['image', 'inpaint'])
        self.assertEqual([m.id for m in result.models], ['z-image-turbo', 'qwen-image-3-edit'])
        generator, editor = result.models
        self.assertTrue(generator.pixel_dimensions)
        self.assertEqual(generator.references, 0)
        self.assertEqual(generator.prompt_limit, 1500)
        self.assertTrue(editor.requires_image)
        self.cache('venice', result.models)
        candidate = curated('venice', editor)
        self.assertEqual(validate_api_tool(candidate).id, editor.id)
        candidate['api']['requireImage'] = False
        with self.assertRaises(ValueError): validate_api_tool(candidate)

    async def test_venice_pixels_and_tiered_generation_contracts(self):
        models = [Model('z-image-turbo', 'Turbo', references=0, pixel_dimensions=True, send_ratio=False),
                  Model('qwen-image-3', 'Qwen', ratios=('3:4',), resolutions=('2K',), references=0)]
        self.cache('venice', models)
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={'images': [base64.b64encode(png()).decode()]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            await VeniceAdapter().submit(client, 'private-key', MediaRequest(models[0].id, 'draw', '2:3', 'standard'))
            await VeniceAdapter().submit(client, 'private-key', MediaRequest(models[1].id, 'draw', '3:4', '2K'))
        first, second = [json.loads(req.content) for req in calls]
        self.assertEqual((first['width'], first['height']), (768, 1152))
        self.assertNotIn('aspect_ratio', first)
        self.assertNotIn('width', second)
        self.assertEqual((second['aspect_ratio'], second['resolution']), ('3:4', '2K'))
        self.assertTrue(all(req.url.path.endswith('/image/generate') for req in calls))

    async def test_venice_edit_binary_contract_and_input_limits(self):
        model = Model('qwen-image-3-edit', 'Edit', ratios=('3:4',), resolutions=('2K',), references=1, requires_image=True)
        self.cache('venice', [model])
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, content=png(), headers={'Content-Type': 'image/png'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            semantic = MediaRequest(model.id, 'edit', '3:4', '2K', images=[('a.png', png(), 'image/png')])
            result = await VeniceAdapter().submit(client, 'private-key', semantic)
            for images in ([], [('a.png', png((16, 16)), 'image/png')]):
                semantic.images = images
                with self.assertRaises(ProviderError): await VeniceAdapter().submit(client, 'private-key', semantic)
        body = json.loads(calls[0].content)
        self.assertEqual(base64.b64decode(body['image']), png())
        self.assertEqual(body['output_format'], 'png')
        self.assertNotIn('return_binary', body)
        self.assertEqual(calls[0].url.path, '/api/v1/image/edit')
        self.assertEqual(result.media[0].data, png())
        self.assertEqual(len(calls), 1)

    async def test_aggregator_http_job_output_and_metadata_lifecycle(self):
        app = FastAPI(); app.include_router(generation_v2.router); app.include_router(outputs.router)
        native = httpx.AsyncClient
        def transport(req):
            encoded = base64.b64encode(png()).decode()
            return httpx.Response(200, json={'images': [encoded]} if req.url.host == 'api.venice.ai' else {'data': [{'b64_json': encoded}]})
        def factory(**kwargs): return native(transport=httpx.MockTransport(transport), **kwargs)
        with patch.object(db, 'DB_PATH', str(Path(self.temp.name) / 'usage.db')), patch.object(jobs, 'OUTPUT_DIR', Path(self.temp.name) / 'outputs'), patch.object(jobs, 'credential', return_value='private-key'), patch.object(jobs, 'metadata_scrubbing_enabled', return_value=True):
            db.init_db(); manager = jobs.MediaJobManager()
            try:
                for provider in ('openrouter', 'venice'):
                    model = Model('vendor/image', 'Image', references=0)
                    self.cache(provider, [model]); value = curated(provider, model)
                    with patch.object(generation_v2, 'get_tool_settings', return_value=value), patch.object(api, 'job_manager', manager), patch.object(jobs.httpx, 'AsyncClient', side_effect=factory):
                        async with native(transport=httpx.ASGITransport(app=app), base_url='http://orange') as client:
                            response = await client.post('/api/generate', data={'tool_id': value['id'], 'prompt': 'an orange'})
                            self.assertEqual(response.status_code, 200, response.text)
                            job_id = response.json()['prompt_id']; await manager.tasks[job_id]
                            output = await client.get('/api/output', params={'prompt_id': job_id, 'type': 'image'})
                            self.assertEqual(output.status_code, 200)
                            with Image.open(BytesIO(output.content)) as image: self.assertNotIn('prompt', image.info)
                            record = db.get_generation_record(job_id)
                            self.assertEqual((record['provider'], record['status']), (provider, 'completed'))
            finally:
                await manager.stop()


class AggregatorEnhancementTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_cloud_uses_shared_keys_fixed_urls_and_text_catalogs(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.method == 'POST': return httpx.Response(200, json={'choices': [{'message': {'content': 'Enhanced'}}]})
            return httpx.Response(200, json={'data': [{'id': 'text-model', 'type': 'text', 'architecture': {'output_modalities': ['text']}},
                {'id': 'image-model', 'type': 'image', 'architecture': {'output_modalities': ['image']}}]})
        native = httpx.AsyncClient
        def factory(**kwargs): return native(transport=httpx.MockTransport(transport), **kwargs)
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'wrong-openai-key'}), patch.object(config, 'credential', side_effect=lambda provider: provider + '-secret'), patch.object(llm.httpx, 'AsyncClient', side_effect=factory):
            for provider, host in [('openrouter', 'openrouter.ai'), ('venice', 'api.venice.ai')]:
                models = await llm.list_llm_models(provider, 'https://wrong.example', 'stale-secret')
                self.assertEqual(models, ['text-model'])
                self.assertEqual(await llm.call_llm(provider, 'https://wrong.example', 'stale-secret', 'text-model', 'Improve', 'orange'), 'Enhanced')
                self.assertTrue(all(req.url.host == host and req.headers['authorization'] == f'Bearer {provider}-secret' for req in calls[-2:]))
            self.assertEqual(calls[2].url.params['type'], 'text')
            self.assertEqual(calls[3].url.path, '/api/v1/chat/completions')

    async def test_missing_shared_credentials_fail_without_network(self):
        with patch.object(config, 'credential', return_value=''), patch.object(llm.httpx, 'AsyncClient') as client:
            for provider in ('openrouter', 'venice'):
                with self.assertRaises(llm.LLMConfigError): await llm.list_llm_models(provider, None, 'stale-secret')
                with self.assertRaises(llm.LLMConfigError): await llm.call_llm(provider, None, None, 'model', 'Improve', 'orange')
            client.assert_not_called()
