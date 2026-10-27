import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

import httpx
from fastapi import FastAPI

from app.api import admin
from app.core import huggingface as hf
from app.core import workflow_install_support as support
from app.core import workflow_install_runner as runner
from app.core import workflow_packs

TOKEN = "hf_testReadTokenOnly123"


class TokenStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "secrets" / "huggingface-token"
        self.token_path = patch.object(hf, "TOKEN_PATH", self.path)
        self.environment = patch.dict(os.environ, {"HF_TOKEN": ""})
        self.token_path.start()
        self.environment.start()
        self.addCleanup(self.token_path.stop)
        self.addCleanup(self.environment.stop)

    def test_saved_token_is_atomic_and_status_is_redacted(self):
        hf.save_token(TOKEN)
        self.assertEqual(hf.get_token(), TOKEN)
        self.assertEqual(hf.token_status(), {"configured": True, "saved": True, "source": "saved"})
        self.assertNotIn(TOKEN, repr(hf.token_status()))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        hf.clear_token()
        self.assertFalse(hf.token_status()["configured"])

    def test_environment_overrides_saved_token_and_survives_removal(self):
        hf.save_token(TOKEN)
        with patch.dict(os.environ, {"HF_TOKEN": "hf_environmentReadToken123"}):
            self.assertEqual(hf.get_token(), "hf_environmentReadToken123")
            hf.clear_token()
            self.assertEqual(hf.token_status(), {"configured": True, "saved": False, "source": "environment"})

    def test_bad_token_does_not_replace_saved_value(self):
        hf.save_token(TOKEN)
        for bad in (None, 42, "", "hf_bad\r\nX-Header:value", "not-a-token"):
            with self.assertRaises(ValueError):
                hf.save_token(bad)
            self.assertEqual(hf.get_token(), TOKEN)

    def test_auth_is_only_attached_to_exact_https_hub_origin(self):
        with patch.object(hf, "get_token", return_value=TOKEN) as read:
            for url in ("http://huggingface.co/a/b", "https://huggingface.co.evil.test/a",
                        "https://cdn.huggingface.co/a", "https://huggingface.co:444/a",
                        "https://user@huggingface.co/a", "https://example.test/model"):
                self.assertEqual(hf.auth_headers(url), {})
            read.assert_not_called()
            self.assertEqual(hf.auth_headers("https://huggingface.co/a/b"), {"Authorization": f"Bearer {TOKEN}"})

    def test_bad_environment_token_error_does_not_echo_secret(self):
        bad = TOKEN + "\ninvalid"
        with patch.dict(os.environ, {"HF_TOKEN": bad}):
            with self.assertRaises(ValueError) as caught:
                hf.auth_headers("https://huggingface.co/a/b")
            self.assertNotIn(TOKEN, str(caught.exception))

    def test_redirects_do_not_forward_token_to_storage_or_http(self):
        original = urllib.request.Request("https://huggingface.co/owner/repo/resolve/main/model")
        original.add_unredirected_header("Authorization", f"Bearer {TOKEN}")
        redirect = hf._HubRedirectHandler()
        same = redirect.redirect_request(original, None, 302, "Found", {}, "https://huggingface.co/owner/repo/file")
        self.assertEqual(same.get_header("Authorization"), f"Bearer {TOKEN}")
        for target in ("https://storage.test/signed-file", "http://huggingface.co/file"):
            external = redirect.redirect_request(original, None, 302, "Found", {}, target)
            self.assertIsNone(external.get_header("Authorization"))
            bounce = redirect.redirect_request(external, None, 302, "Found", {}, "https://huggingface.co/other")
            self.assertIsNone(bounce.get_header("Authorization"))
        ordinary_header = urllib.request.Request(original.full_url, headers={"Authorization": f"Bearer {TOKEN}"})
        external = redirect.redirect_request(ordinary_header, None, 302, "Found", {}, "https://storage.test/file")
        self.assertIsNone(external.get_header("Authorization"))

    def test_authenticated_download_uses_header_without_url_credentials(self):
        hf.save_token(TOKEN)
        opener = Mock()
        with patch.object(hf.urllib.request, "build_opener", return_value=opener):
            hf.open_model_download("https://huggingface.co/owner/repo/resolve/main/file")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        self.assertNotIn(TOKEN, request.full_url)
        self.assertNotIn("Authorization", request.headers)

    def test_gated_error_is_actionable_and_does_not_expose_token(self):
        hf.save_token(TOKEN)
        denied = urllib.error.HTTPError("https://huggingface.co/a/b", 403, TOKEN, {}, None)
        opener = Mock()
        opener.open.side_effect = denied
        with patch.object(hf.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(ValueError, "accept the model's terms") as caught:
                hf.open_model_download("https://huggingface.co/a/b")
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_both_installers_download_with_saved_token_without_recording_it(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": "7"}
        hf.save_token(TOKEN)
        opener = Mock()
        opener.open.side_effect = [Response(b"weights"), Response(b"weights")]
        url = "https://huggingface.co/owner/repo/resolve/main/test.safetensors"
        with patch.object(hf.urllib.request, "build_opener", return_value=opener), \
             patch.object(runner, "is_cancel_requested", return_value=False), \
             patch.object(runner, "update_file_progress") as progress:
            direct = Path(self.directory.name) / "direct.safetensors"
            queued = Path(self.directory.name) / "queued.safetensors"
            workflow_packs._download_file(url, str(direct))
            runner._download_with_progress(url, str(queued), "test-job", queued.name)
            self.assertEqual(direct.read_bytes(), b"weights")
            self.assertEqual(queued.read_bytes(), b"weights")
            self.assertNotIn(TOKEN, repr(progress.call_args_list))
        for call in opener.open.call_args_list:
            self.assertEqual(call.args[0].get_header("Authorization"), f"Bearer {TOKEN}")


class TokenAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_endpoints_require_admin_and_never_return_token(self):
        app = FastAPI()
        app.include_router(admin.router)
        with tempfile.TemporaryDirectory() as directory, patch.object(hf, "TOKEN_PATH", Path(directory) / "token"), \
             patch.dict(os.environ, {"HF_TOKEN": ""}), patch.object(admin, "load_config", return_value={"adminKey": "admin-test"}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://orange") as client:
                self.assertEqual((await client.get("/api/admin/huggingface-token")).status_code, 401)
                unauthorized = await client.post("/api/admin/huggingface-token", json={"token": TOKEN})
                self.assertEqual(unauthorized.status_code, 401)
                self.assertFalse(hf.token_status()["configured"])
                headers = {"Authorization": "Bearer admin-test"}
                saved = await client.post("/api/admin/huggingface-token", json={"token": TOKEN}, headers=headers)
                self.assertEqual(saved.status_code, 200)
                self.assertNotIn(TOKEN, saved.text)
                status = await client.get("/api/admin/huggingface-token", headers=headers)
                self.assertTrue(status.json()["configured"])
                self.assertNotIn(TOKEN, status.text)
                config = await client.get("/api/admin/config", headers=headers)
                self.assertNotIn(TOKEN, config.text)
                invalid = await client.post("/api/admin/huggingface-token", json={"token": "invalid"}, headers=headers)
                self.assertEqual(invalid.status_code, 400)
                removed = await client.delete("/api/admin/huggingface-token", headers=headers)
                self.assertFalse(removed.json()["configured"])

    async def test_size_requests_strip_token_on_cross_origin_redirects(self):
        seen = []
        def handle(request):
            seen.append((request.url.host, request.headers.get("Authorization")))
            if request.url.host == "huggingface.co":
                return httpx.Response(302, headers={"Location": "https://storage.test/file"})
            return httpx.Response(200, headers={"Content-Length": "123"})
        url = "https://huggingface.co/test/size-redirect"
        support._size_cache.pop(url, None)
        with patch.object(hf, "get_token", return_value=TOKEN):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
                size = await support._remote_size(client, url)
        self.assertEqual(size, 123)
        self.assertEqual(seen, [("huggingface.co", f"Bearer {TOKEN}"), ("storage.test", None)])

    async def test_denied_size_is_retried_after_access_changes(self):
        responses = iter([401, 200])
        def handle(request):
            return httpx.Response(next(responses), headers={"Content-Length": "20"})
        url = "https://huggingface.co/test/retry-access"
        support._size_cache.pop(url, None)
        with patch.object(hf, "get_token", return_value=""):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                self.assertIsNone(await support._remote_size(client, url))
                self.assertEqual(await support._remote_size(client, url), 20)
