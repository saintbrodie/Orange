import asyncio
import base64
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from starlette.datastructures import Headers
from PIL import Image, PngImagePlugin
from starlette.requests import Request

from app.api import generation_v2, media_providers as api, outputs, setup, status
from app.core import database as db, media_jobs as jobs, media_provider_config as config
from app.core.config_validation import validate_config
from app.core.media_providers import (
    ADAPTERS, GoogleAdapter, Media, MediaRequest, OpenAIAdapter, ProviderError,
    ProviderResult, _request, model_for, validate_api_tool,
)
from app.core.public_config import build_public_config


def tool(provider="google", video=False):
    return {"id": "cloud-tool", "name": "Create something", "provider": provider,
            "model": "gemini-omni-1.2-flash" if video else "gemini-nano-banana-2.1" if provider == "google" else "gpt-image-2.6-sunburst",
            "outputType": "video" if video else "image",
            "api": {"ratios": ["16:9"] if video else ["1:1"], "references": 2, "requireImage": False,
                    "resolutions": ["720p"] if video else ["1K"] if provider == "google" else ["standard"],
                    "defaultResolution": "720p" if video else "1K" if provider == "google" else "standard",
                    **({"durations": [5, 10, 15], "defaultDuration": 10} if video else {})}}


def png():
    buffer = BytesIO()
    metadata = PngImagePlugin.PngInfo(); metadata.add_text("prompt", "private metadata")
    Image.new("RGB", (16, 16), "orange").save(buffer, "PNG", pnginfo=metadata)
    return buffer.getvalue()


def request():
    return Request({"type": "http", "method": "POST", "path": "/api/generate", "headers": [], "client": ("127.0.0.1", 1234)})


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_lists_openai_models_without_testing_each_model(self):
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={"data": [{"id": "gpt-image-2.6-flare"}, {"id": "text-model"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            models = await OpenAIAdapter().test(client, "secret")
        self.assertEqual(models, ["gpt-image-2.6-flare", "text-model"])
        self.assertEqual([req.url.path for req in calls], ["/v1/models"])

    async def test_google_model_discovery_follows_pagination(self):
        calls = []
        def transport(req):
            calls.append(req)
            if len(calls) == 1:
                return httpx.Response(200, json={"models": [{"name": "models/gemini-nano-banana-2.1"}], "nextPageToken": "next"})
            return httpx.Response(200, json={"models": [{"name": "models/gemini-omni-1.2-flash"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            models = await GoogleAdapter().test(client, "secret")
        self.assertEqual(models, ["gemini-nano-banana-2.1", "gemini-omni-1.2-flash"])
        self.assertEqual(calls[1].url.params["pageToken"], "next")
        self.assertTrue(all(req.method == "GET" and req.url.path == "/v1beta/models" for req in calls))

    async def test_discovery_rejects_repeated_page_token(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"models": [], "nextPageToken": "again"}))) as client:
            with self.assertRaises(ProviderError): await GoogleAdapter().test(client, "secret")

    async def test_openai_generation_and_edit_contracts(self):
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}], "usage": {"input_tokens": 7, "secret": "do not save"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = OpenAIAdapter()
            semantic = MediaRequest("gpt-image-2.6-sunburst", "a sunset", "1:1", "standard")
            result = await adapter.submit(client, "secret", semantic)
            semantic.images = [("ref.png", png(), "image/png")]
            await adapter.submit(client, "secret", semantic)
        self.assertEqual(calls[0].url.path, "/v1/images/generations")
        self.assertEqual(calls[1].url.path, "/v1/images/edits")
        body = json.loads(calls[1].content)
        self.assertTrue(body["images"][0]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(result.usage, {"input_tokens": 7})
        self.assertNotIn("response_format", body)

    async def test_google_uses_rest_steps_not_sdk_convenience_fields(self):
        calls = []
        def transport(req):
            calls.append(req)
            return httpx.Response(200, json={"status": "completed", "usage": {"total_input_tokens": 8, "total_output_tokens": 10}, "steps": [
                {"type": "user_input", "content": [{"type": "image", "data": "ignore"}]},
                {"type": "model_output", "content": [{"type": "image", "mime_type": "image/png", "data": base64.b64encode(png()).decode()}]}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            result = await GoogleAdapter().submit(client, "secret", MediaRequest("gemini-nano-banana-2.1", "edit", "1:1", "2K", images=[("a.png", png(), "image/png")]))
        self.assertEqual(len(result.media), 1)
        self.assertEqual(result.usage, {"input_tokens": 8, "output_tokens": 10})
        body = json.loads(calls[0].content)
        self.assertEqual(body["response_format"], {"type": "image", "aspect_ratio": "1:1", "image_size": "2K"})
        self.assertFalse(body["store"])
        self.assertEqual(calls[0].headers["Api-Revision"], "2026-05-20")
        self.assertNotIn("secret", str(calls[0].url))

    async def test_omni_uri_poll_and_download(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.method == "POST":
                return httpx.Response(200, json={"steps": [{"type": "model_output", "content": [{"type": "video", "uri": "files/video-123"}]}]})
            if req.url.path.endswith(":download"):
                return httpx.Response(200, content=b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00")
            return httpx.Response(200, json={"state": "ACTIVE"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            adapter = GoogleAdapter()
            result = await adapter.submit(client, "secret", MediaRequest("gemini-omni-1.2-flash", "a lake", "16:9", "720p", 15))
            final = await adapter.poll(client, "secret", result.remote_id)
        self.assertEqual(json.loads(calls[0].content)["response_format"]["duration"], "15s")
        self.assertEqual(final.media[0].mime, "video/mp4")
        self.assertEqual(calls[-1].url.params["alt"], "media")
        self.assertNotIn("secret", str(calls[-1].url))

    async def test_pending_and_failed_video_files(self):
        adapter = GoogleAdapter()
        for state in ("PROCESSING", "FAILED"):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"state": state}))) as client:
                if state == "FAILED":
                    with self.assertRaises(ProviderError): await adapter.poll(client, "key", "files/a")
                else:
                    self.assertEqual((await adapter.poll(client, "key", "files/a")).remote_id, "files/a")

    async def test_uncertain_post_is_never_retried_and_errors_are_redacted(self):
        for failure in (httpx.ReadTimeout("secret"), httpx.WriteError("secret")):
            client = Mock(); client.request = AsyncMock(side_effect=failure)
            with self.assertRaises(ProviderError) as caught:
                await _request(client, "POST", "https://api.openai.com/v1/images/generations")
            self.assertEqual(client.request.await_count, 1)
            self.assertNotIn("secret", str(caught.exception))
        client = Mock(); client.request = AsyncMock(return_value=httpx.Response(500, text="secret"))
        with self.assertRaises(ProviderError) as caught: await _request(client, "POST", "https://api.openai.com")
        self.assertEqual(client.request.await_count, 1)
        self.assertNotIn("secret", str(caught.exception))

    async def test_safe_connect_throttle_and_get_retries(self):
        client = Mock()
        client.request = AsyncMock(side_effect=[httpx.ConnectTimeout("connect"), httpx.Response(429), httpx.Response(200)])
        with patch("asyncio.sleep", new=AsyncMock()):
            await _request(client, "POST", "https://api.openai.com")
        self.assertEqual(client.request.await_count, 3)
        client.request = AsyncMock(side_effect=[httpx.Response(503), httpx.Response(200)])
        with patch("asyncio.sleep", new=AsyncMock()): await _request(client, "GET", "https://api.openai.com")
        self.assertEqual(client.request.await_count, 2)

    async def test_no_credentials_forwarded_to_redirects(self):
        for location in ("files/video-123", "https://generativelanguage.googleapis.com/v1beta/files/video-123", "https://generativelanguage.googleapis.com/v1beta/files/video-123:download?alt=media"):
            self.assertEqual(GoogleAdapter.file_id(location), "files/video-123")
        for location in ("https://evil.example/video.mp4", "http://generativelanguage.googleapis.com/a", "files/../../secret", "files/a?key=secret"):
            with self.assertRaises(ProviderError): GoogleAdapter.file_id(location)

    async def test_video_download_redirects_strip_api_credentials(self):
        calls = []
        def transport(req):
            calls.append(req)
            if req.url.path.endswith(":download"):
                return httpx.Response(302, headers={"location": "https://storage.googleapis.com/media/video.mp4?signature=example"})
            if req.url.host == "storage.googleapis.com":
                return httpx.Response(200, content=b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00")
            return httpx.Response(200, json={"state": "ACTIVE"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            await GoogleAdapter().poll(client, "secret", "files/abc")
        self.assertEqual(calls[-1].url.host, "storage.googleapis.com")
        self.assertNotIn("x-goog-api-key", calls[-1].headers)
        self.assertNotIn("Api-Revision", calls[-1].headers)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}))) as client:
            with self.assertRaises(ProviderError): await _request(client, "GET", "https://api.openai.com")

    async def test_empty_or_filtered_output_is_an_error(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={}))) as client:
            for provider, model in ((GoogleAdapter(), "gemini-nano-banana-2.1"), (OpenAIAdapter(), "gpt-image-2.6-flare")):
                with self.assertRaises(ProviderError): await provider.submit(client, "key", MediaRequest(model, "prompt", "1:1", "1K"))


class ConfigTests(unittest.TestCase):
    def test_app_wide_metadata_setting_defaults_on_and_validates(self):
        from app.core.utils import metadata_scrubbing_enabled
        for value, expected in (({}, True), ({"scrubMetadata": True}, True), ({"scrubMetadata": False}, False)):
            with patch("app.core.config.load_config", return_value=value):
                self.assertEqual(metadata_scrubbing_enabled(), expected)
        self.assertTrue(validate_config({"scrubMetadata": "false"})["errors"])

    def test_mp4_metadata_is_blanked_without_moving_media(self):
        def box(kind, payload): return (len(payload)+8).to_bytes(4, 'big') + kind + payload
        original = box(b'ftyp', b'isom0000') + box(b'moov', box(b'udta', b'private metadata')) + box(b'mdat', b'media')
        clean = jobs._scrub_mp4(original)
        self.assertEqual(len(clean), len(original))
        self.assertNotIn(b'private metadata', clean)
        self.assertTrue(clean.endswith(box(b'mdat', b'media')))

    def test_capability_validation_and_public_projection(self):
        for value in (tool(), tool("openai"), tool(video=True)):
            self.assertEqual(validate_config({"tools": [value], "apiOnly": True})["errors"], [])
            public = build_public_config({"tools": [value], "apiProviders": {"apiKey": "secret"}})
            text = json.dumps(public)
            self.assertNotIn("secret", text)
            self.assertNotIn(value["model"], text)
            self.assertTrue(public["tools"][0]["nodeMapping"]["prompt"])

    def test_rejects_unsupported_models_controls_and_types(self):
        for path, value in (("model", "gpt-image-2.6"), ("provider", "other"), ("outputType", "audio"), ("workflowFile", "x.json")):
            candidate = tool(); candidate[path] = value
            self.assertTrue(validate_config({"tools": [candidate]})["errors"])
        for key, value in (("ratios", ["17:2"]), ("references", 99), ("resolutions", []), ("temperature", 0.8)):
            candidate = tool(); candidate["api"][key] = value
            self.assertTrue(validate_config({"tools": [candidate]})["errors"])

    def test_credentials_are_separate_from_settings_and_never_returned(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "SETTINGS_PATH", Path(directory) / "providers.json"), patch.object(config, "_vault") as vault, patch.dict(os.environ, {}, clear=True):
            config.save_provider("openai", {"enabled": True, "models": ["gpt-image-2.6-flare"], "apiKey": "secret"})
            vault.assert_called_with("openai", "set_password", "secret")
            self.assertNotIn("secret", config.SETTINGS_PATH.read_text())
            vault.return_value = "secret"
            self.assertNotIn("secret", json.dumps(config.public_settings()))
            config.save_provider("openai", {"enabled": True, "models": ["gpt-image-2.6-flare"], "apiKey": ""})
            self.assertEqual(vault.call_count, 2 + len(config.ENV_KEYS))  # credential comparison/save plus two status lookups

    def test_environment_wins_without_vault_access(self):
        with patch.dict(os.environ, {"ORANGE_GOOGLE_API_KEY": "env-secret"}), patch.object(config, "_vault") as vault:
            self.assertEqual(config.credential("google"), "env-secret")
            vault.assert_not_called()

    def test_invalid_provider_config_does_not_write_credentials(self):
        for payload in ({"enabled": "true", "models": []}, {"enabled": True, "models": ["invented-model"], "apiKey": "secret"},
                        {"enabled": True, "models": [], "rates": {"gpt-image-2.6-flare": float('nan')}},
                        {"enabled": True, "models": [], "baseUrl": "http://127.0.0.1"}):
            with patch.object(config, "_vault") as vault:
                with self.assertRaises(ValueError): config.save_provider("openai", payload)
                vault.assert_not_called()

    def test_api_tool_can_be_modify_target(self):
        value = tool()
        self.assertEqual(validate_config({"tools": [value], "modifyTool": value["id"]})["errors"], [])


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_switch_preserves_original_when_disabled(self):
        job_id = 'api-' + 'a' * 32
        original = png()
        manifest = jobs._store_outputs(job_id, [Media(original, 'image/png')], 'image', scrub=False)
        self.assertEqual(jobs.output_path(manifest[0]['filename']).read_bytes(), original)
        manifest = jobs._store_outputs(job_id, [Media(original, 'image/png')], 'image')
        with Image.open(jobs.output_path(manifest[0]['filename'])) as image:
            self.assertNotIn('prompt', image.info)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(db, "DB_PATH", str(Path(self.temp.name) / "usage.db")); self.path_patch.start()
        self.output_patch = patch.object(jobs, "OUTPUT_DIR", Path(self.temp.name) / "outputs"); self.output_patch.start()
        db.init_db(); self.manager = jobs.MediaJobManager()
        self.credential = patch.object(jobs, "credential", return_value="key"); self.credential.start()

    async def asyncTearDown(self):
        await self.manager.stop()
        self.credential.stop(); self.output_patch.stop(); self.path_patch.stop(); self.temp.cleanup()

    async def submit(self, adapter=None, video=False):
        value = tool(video=video)
        fake = adapter or Mock(submit=AsyncMock(return_value=ProviderResult(media=[Media(png(), "image/png")], usage={"input_tokens": 9})))
        with patch.dict(ADAPTERS, {"google": fake}):
            result = self.manager.submit("google", model_for("google", value["model"]), value["id"], MediaRequest(value["model"], "hello", "16:9" if video else "1:1", "720p" if video else "1K", 10 if video else None), "127.0.0.1")
            await self.manager.tasks[result["prompt_id"]]
        return result["prompt_id"]

    async def test_lifecycle_local_outputs_usage_and_deletion(self):
        job_id = await self.submit()
        self.assertEqual(jobs.get_job(job_id)["status"], "completed")
        row = db.get_generation_record(job_id)
        self.assertEqual((row["provider"], row["model"], row["status"]), ("google", "gemini-nano-banana-2.1", "completed"))
        self.assertEqual(json.loads(row["usage_json"]), {"input_tokens": 9})
        with patch.object(outputs, "get_backend_client", AsyncMock()) as backend:
            listing = await outputs.list_outputs(job_id, type="image")
            media = await outputs.get_media(job_id, type="image", index=0)
            backend.assert_not_called()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["index"], 0)
        with Image.open(media.path) as image: self.assertNotIn("prompt", image.info)
        self.assertTrue(jobs.delete_job(job_id))
        self.assertIsNone(jobs.get_job(job_id)); self.assertIsNone(db.get_generation_record(job_id))
        self.assertFalse(list(jobs.OUTPUT_DIR.glob("*")))

    async def test_local_video_and_status_stream(self):
        job_id = await self.submit(Mock(submit=AsyncMock(return_value=ProviderResult(media=[Media(b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00", "video/mp4")]))), video=True)
        client = Mock(); client.is_disconnected = AsyncMock(return_value=False)
        self.assertEqual([json.loads(e) async for e in jobs.status_events(client, job_id)], [{"status": "completed"}])
        self.assertEqual((await outputs.list_outputs(job_id, type="video"))["items"][0]["media_type"], "video/mp4")
        with self.assertRaises(HTTPException): await outputs.get_media(job_id, type="video", index=1)

    async def test_failures_are_persisted_and_secrets_are_discarded(self):
        job_id = await self.submit(Mock(submit=AsyncMock(side_effect=RuntimeError("secret"))))
        row = db.get_generation_record(job_id)
        self.assertEqual(row["status"], "failed")
        self.assertNotIn("secret", row["error"])
        with self.assertRaises(HTTPException): await outputs.list_outputs(job_id, type="image")

    async def test_invalid_outputs_do_not_leave_partial_files(self):
        job_id = await self.submit(Mock(submit=AsyncMock(return_value=ProviderResult(media=[Media(png(), "image/png"), Media(b"bad", "image/png")]))))
        self.assertEqual(jobs.get_job(job_id)["status"], "failed")
        self.assertFalse(list(jobs.OUTPUT_DIR.glob("*")))
        for filename in ("../secret", "api-a.png", "/etc/passwd"):
            with self.assertRaises(ValueError): jobs.output_path(filename)

    async def test_restart_never_resubmits_uncertain_request(self):
        adapter = Mock(submit=AsyncMock())
        with patch.object(self.manager, "_schedule"):
            result = self.manager.submit("google", model_for("google", "gemini-nano-banana-2.1"), "tool", MediaRequest("gemini-nano-banana-2.1", "p", "1:1", "1K"), "ip")
        with patch.dict(ADAPTERS, {"google": adapter}): await self.manager.start()
        self.assertEqual(jobs.get_job(result["prompt_id"])["status"], "interrupted")
        adapter.submit.assert_not_called()

    async def test_restart_resumes_only_known_remote_video(self):
        with patch.object(self.manager, "_schedule"):
            result = self.manager.submit("google", model_for("google", "gemini-omni-1.2-flash"), "tool", MediaRequest("gemini-omni-1.2-flash", "p", "16:9", "720p", 10), "ip")
        job_id = result["prompt_id"]
        jobs._update(job_id, "processing", remote_id="files/abc")
        adapter = Mock(poll=AsyncMock(return_value=ProviderResult(media=[Media(b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00", "video/mp4")])))
        with patch.dict(ADAPTERS, {"google": adapter}), patch("asyncio.sleep", new=AsyncMock()):
            await self.manager.start(); await self.manager.tasks[job_id]
        self.assertEqual(jobs.get_job(job_id)["status"], "completed")
        adapter.submit.assert_not_called(); adapter.poll.assert_awaited_once()

    async def test_expired_jobs_time_out_without_provider_call(self):
        with patch.object(self.manager, "_schedule"):
            result = self.manager.submit("google", model_for("google", "gemini-nano-banana-2.1"), "tool", MediaRequest("gemini-nano-banana-2.1", "p", "1:1", "1K"), "ip")
        job_id = result["prompt_id"]
        with db._connect() as conn: conn.execute("UPDATE media_jobs SET created=? WHERE id=?", (time.time() - 10000, job_id))
        await self.manager._run(job_id, None)
        self.assertEqual(jobs.get_job(job_id)["status"], "timed_out")

    async def test_http_generation_to_local_download_with_real_adapter(self):
        app = FastAPI(); app.include_router(generation_v2.router); app.include_router(outputs.router)
        cloud_calls = []
        def provider_transport(req):
            cloud_calls.append(req)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})
        native_client = httpx.AsyncClient
        def client_factory(*args, **kwargs):
            return native_client(transport=httpx.MockTransport(provider_transport), **kwargs)
        value = tool("openai")
        with patch.object(generation_v2, "get_tool_settings", return_value=value), patch.object(config, "ready", return_value=True), patch.object(api, "job_manager", self.manager), patch.object(jobs.httpx, "AsyncClient", side_effect=client_factory):
            async with native_client(transport=httpx.ASGITransport(app=app), base_url="http://orange") as client:
                response = await client.post("/api/generate", data={"tool_id": value["id"], "prompt": "test image", "aspect_ratio": "1:1", "resolution": "standard"})
                self.assertEqual(response.status_code, 200)
                job_id = response.json()["prompt_id"]
                await self.manager.tasks[job_id]
                output = await client.get("/api/output", params={"prompt_id": job_id, "type": "image"})
                self.assertEqual(output.status_code, 200)
                self.assertEqual(output.headers["content-type"], "image/png")
                self.assertEqual(Image.open(BytesIO(output.content)).size, (16, 16))
        self.assertEqual(len(cloud_calls), 1)
        self.assertEqual(cloud_calls[0].url.host, "api.openai.com")

    async def test_concurrency_and_queue_bound(self):
        release = asyncio.Event(); two_started = asyncio.Event()
        active, peak = 0, 0
        async def submit(*args):
            nonlocal active, peak
            active += 1; peak = max(peak, active)
            if active == 2: two_started.set()
            await release.wait()
            active -= 1
            return ProviderResult(media=[Media(png(), "image/png")])
        adapter = Mock(submit=submit)
        with patch.dict(ADAPTERS, {"google": adapter}), patch.object(jobs, "MAX_JOBS", 3):
            ids = [self.manager.submit("google", model_for("google", "gemini-nano-banana-2.1"), "tool", MediaRequest("gemini-nano-banana-2.1", "p", "1:1", "1K"), "ip")["prompt_id"] for _ in range(3)]
            with self.assertRaises(ProviderError): self.manager.submit("google", model_for("google", "gemini-nano-banana-2.1"), "tool", MediaRequest("gemini-nano-banana-2.1", "p", "1:1", "1K"), "ip")
            await asyncio.wait_for(two_started.wait(), 2)
            self.assertEqual(jobs.get_job(ids[-1])["status"], "queued")
            self.assertEqual(jobs.queue_position(jobs.get_job(ids[-1])), 1)
            release.set(); await asyncio.gather(*self.manager.tasks.values())
        self.assertEqual(peak, 2)
        self.assertTrue(all(jobs.get_job(job_id)["status"] == "completed" for job_id in ids))


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_test_discovers_and_caches_supported_models(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "SETTINGS_PATH", Path(directory) / "providers.json"), patch.object(config, "credential", return_value="secret"), patch.object(ADAPTERS["google"], "test", AsyncMock(return_value=["gemini-nano-banana-2.1", "text-model", "secret"] )) as listing:
            config.save_provider("google", {"enabled": True})
            result = await api.test_provider("google", _=True)
            self.assertEqual(result["models"], [{"id": "gemini-nano-banana-2.1", "name": "Nano Banana 2.1"}])
            self.assertNotIn("secret", json.dumps(result))
            self.assertEqual(config.settings()["google"]["discoveredModels"], ["gemini-nano-banana-2.1"])
            self.assertNotIn("secret", config.SETTINGS_PATH.read_text())
            self.assertIsNotNone(config.public_settings()[0]["discoveredAt"])
            self.assertEqual(listing.await_count, 1)
            # Provider availability is no longer a second, manually curated model gate.
            self.assertTrue(config.enabled("google", "gemini-omni-1.2-flash"))

    async def test_credential_change_clears_discovery_and_save_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "SETTINGS_PATH", Path(directory) / "providers.json"), patch.object(config, "credential", return_value="old-key"), patch.object(config, "_vault", return_value="old-key"):
            config.save_provider("google", {"enabled": True})
            config.save_discovery("google", ["gemini-nano-banana-2.1"], "old-key")
            config.save_provider("google", {"enabled": True, "apiKey": ""})
            self.assertIn("discoveredAt", config.settings()["google"])
            config.save_provider("google", {"enabled": True, "apiKey": "new-key"})
            self.assertNotIn("discoveredAt", config.settings()["google"])
            self.assertNotIn("discoveredModels", config.settings()["google"])

    async def test_discovery_empty_failure_and_unknown_provider(self):
        with patch.object(config, "credential", return_value="key"), patch.object(ADAPTERS["openai"], "test", AsyncMock(return_value=[])), patch.object(config, "save_discovery", return_value=[]):
            result = await api.test_provider("openai", _=True)
            self.assertEqual(result["status"], "connected")
            self.assertEqual(result["models"], [])
        with self.assertRaises(HTTPException) as caught: await api.test_provider("unknown", _=True)
        self.assertEqual(caught.exception.status_code, 400)
        with patch.object(config, "credential", return_value="key"), patch.object(ADAPTERS["openai"], "test", AsyncMock(side_effect=ProviderError("Provider authentication failed."))):
            with self.assertRaises(HTTPException) as caught: await api.test_provider("openai", _=True)
            self.assertEqual(caught.exception.status_code, 502)

    async def test_reference_uploads_normalize_mime_and_remove_metadata(self):
        upload = UploadFile(BytesIO(png()), filename="user-file.png", headers=Headers({"content-type": "image/png"}))
        filename, data, mime = await api._reference_image(upload)
        self.assertEqual((filename, mime), ("reference.png", "image/png"))
        with Image.open(BytesIO(data)) as image: self.assertNotIn("prompt", image.info)

    async def test_cloud_generation_bypasses_comfy_and_rejects_invalid_inputs(self):
        value = tool()
        with patch.object(generation_v2, "get_tool_settings", return_value=value), patch.object(config, "ready", return_value=True), patch.object(api.job_manager, "submit", return_value={"prompt_id": "job"}) as submit, patch.object(generation_v2, "get_best_backend", AsyncMock()) as comfy:
            result = await generation_v2.generate_v2(request(), "cloud-tool", "hello", "1:1", None, None, None, "1K")
            self.assertEqual(result["prompt_id"], "job"); comfy.assert_not_called()
            self.assertEqual(submit.call_count, 1)
            with self.assertRaises(HTTPException): await generation_v2.generate_v2(request(), "cloud-tool", "hello", "bad", None, None, None, "1K")
            with self.assertRaises(HTTPException): await generation_v2.generate_v2(request(), "cloud-tool", "hello", "1:1", None, None, None, "4K")

    async def test_admin_provider_routes_require_auth_and_redact(self):
        app = FastAPI(); app.include_router(api.router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for method, path, body in (("GET", "/api/admin/providers", None), ("PUT", "/api/admin/providers/openai", {}), ("POST", "/api/admin/providers/openai/test", {})):
                response = await client.request(method, path, json=body)
                self.assertEqual(response.status_code, 401)

    async def test_api_only_setup_and_health_do_not_contact_comfy(self):
        with patch.object(setup, "setup_required", return_value=True), patch.object(setup, "load_config", return_value={}), patch.object(setup, "save_config") as save, patch.object(setup, "mark_setup_complete"), patch.object(setup, "_read_backend_metadata", AsyncMock()) as comfy:
            result = await setup.complete_setup({"adminKey": "password-123", "apiOnly": True}, request())
            self.assertEqual(result["status"], "complete"); comfy.assert_not_called()
            self.assertTrue(save.call_args.args[0]["apiOnly"])
        with patch.object(status, "get_tool_settings", return_value=tool()), patch.object(config, "ready", return_value=True), patch.object(status, "get_backend_client", AsyncMock()) as backend:
            self.assertEqual((await status.get_health("cloud-tool"))["status"], "ready"); backend.assert_not_called()
