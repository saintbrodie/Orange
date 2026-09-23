import unittest
from unittest import mock

import httpx

from app.core import managed_prompt_enhancer as managed
from app.core.config_validation import validate_config
from app.core.llm import call_llm


class _FakeAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        self.__class__.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.__class__.calls.append((url, kwargs))
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "enhanced locally"}}]},
            request=request,
        )


class ManagedPromptEnhancerTests(unittest.TestCase):
    def test_packaged_runtime_assets_cover_primary_platforms(self):
        cases = [
            ("Windows", "AMD64", "win-cpu-x64.zip"),
            ("Linux", "x86_64", "ubuntu-x64.tar.gz"),
            ("Darwin", "arm64", "macos-arm64.tar.gz"),
        ]
        for system, machine, suffix in cases:
            with self.subTest(system=system, machine=machine), mock.patch.object(
                managed.platform, "system", return_value=system
            ), mock.patch.object(managed.platform, "machine", return_value=machine):
                asset = managed.runtime_asset()
                self.assertIsNotNone(asset)
                self.assertTrue(asset["name"].endswith(suffix))
                self.assertEqual(len(asset["sha256"]), 64)

    def test_model_metadata_is_pinned_and_text_only(self):
        self.assertEqual(managed.MANAGED_MODEL_ID, "gemma-4-e2b")
        self.assertEqual(managed.MANAGED_MODEL_BYTES, 3349516256)
        self.assertEqual(
            managed.MANAGED_MODEL_SHA256,
            "fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634",
        )
        self.assertIn(managed.MANAGED_MODEL_REVISION, managed.MANAGED_MODEL_URL)
        self.assertNotIn("mmproj", managed.MANAGED_MODEL_URL.lower())

    def test_config_validation_accepts_managed_provider(self):
        config = {
            "adminKey": "password123",
            "comfyServers": [{"url": "http://127.0.0.1:8188", "priority": 1}],
            "llm": {
                "enabled": True,
                "provider": "managed",
                "baseUrl": "",
                "apiKey": "",
                "model": "gemma-4-e2b",
            },
            "tools": [],
        }
        validation = validate_config(config)
        self.assertEqual(validation["errors"], [])


class ManagedPromptEnhancerCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_managed_provider_ignores_stale_external_model_settings(self):
        with mock.patch(
            "app.core.managed_prompt_enhancer.ensure_server_ready",
            new=mock.AsyncMock(),
        ), mock.patch("app.core.llm.httpx.AsyncClient", _FakeAsyncClient):
            result = await call_llm(
                provider="managed",
                base_url="https://api.openai.com/v1",
                api_key="should-not-be-used",
                model="stale-external-model",
                system_prompt="Enhance the prompt.",
                prompt="a cat",
            )

        self.assertEqual(result, "enhanced locally")
        url, kwargs = _FakeAsyncClient.calls[0]
        self.assertEqual(url, "http://127.0.0.1:7071/v1/chat/completions")
        self.assertEqual(kwargs["json"]["model"], "gemma-4-e2b")
        self.assertNotIn("Authorization", kwargs.get("headers", {}))


if __name__ == "__main__":
    unittest.main()
