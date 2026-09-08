import os
import unittest
from unittest.mock import patch

import httpx

from app.core.llm import (
    LLMConfigError,
    LLMError,
    call_llm,
    validate_base_url,
    validate_model,
)


class _FakeAsyncClient:
    response = None
    calls = []

    def __init__(self, *args, **kwargs):
        self.__class__.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.__class__.calls.append(("POST", url, kwargs))
        return self.__class__.response

    async def get(self, url, **kwargs):
        self.__class__.calls.append(("GET", url, kwargs))
        return self.__class__.response


def _response(status=200, json_data=None, text=None, url="http://provider.local/api"):
    request = httpx.Request("POST", url)
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=request)
    return httpx.Response(status, text=text or "", request=request)


class LLMValidationTests(unittest.TestCase):
    def test_invalid_base_scheme_rejected(self):
        with self.assertRaises(LLMConfigError):
            validate_base_url("file:///tmp/model")

    def test_base_url_credentials_rejected(self):
        with self.assertRaises(LLMConfigError):
            validate_base_url("http://user:pass@localhost:1234/v1")

    def test_base_url_query_rejected(self):
        with self.assertRaises(LLMConfigError):
            validate_base_url("http://localhost:1234/v1?token=secret")

    def test_invalid_model_rejected(self):
        with self.assertRaises(LLMConfigError):
            validate_model("")
        with self.assertRaises(LLMConfigError):
            validate_model("bad\nmodel")
        with self.assertRaises(LLMConfigError):
            validate_model("x" * 257)


class LLMCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_default_requires_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
            with self.assertRaises(LLMConfigError):
                await call_llm("openai", None, None, "model", "system", "prompt")

    async def test_local_openai_compatible_server_can_be_keyless(self):
        _FakeAsyncClient.response = _response(
            json_data={"choices": [{"message": {"content": "enhanced"}}]}
        )
        with patch("app.core.llm.httpx.AsyncClient", _FakeAsyncClient):
            result = await call_llm(
                "openai",
                "http://127.0.0.1:1234/v1",
                None,
                "local-model",
                "system",
                "prompt",
            )
        self.assertEqual(result, "enhanced")
        method, url, kwargs = _FakeAsyncClient.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://127.0.0.1:1234/v1/chat/completions")
        self.assertNotIn("Authorization", kwargs.get("headers", {}))

    async def test_provider_error_body_redacts_api_key(self):
        secret = "sk-super-secret-test-key"
        _FakeAsyncClient.response = _response(status=401, text=f"invalid credential {secret}")
        with patch("app.core.llm.httpx.AsyncClient", _FakeAsyncClient):
            with self.assertRaises(LLMError) as ctx:
                await call_llm(
                    "openai",
                    "https://api.openai.com/v1",
                    secret,
                    "model",
                    "system",
                    "prompt",
                )
        self.assertNotIn(secret, ctx.exception.technical_message)
        self.assertNotIn(secret, ctx.exception.public_message)
        self.assertEqual(ctx.exception.public_message, "Prompt enhancement service returned an error.")

    async def test_invalid_provider_shape_returns_safe_error(self):
        _FakeAsyncClient.response = _response(json_data={"choices": []})
        with patch("app.core.llm.httpx.AsyncClient", _FakeAsyncClient):
            with self.assertRaises(LLMError) as ctx:
                await call_llm(
                    "openai",
                    "http://127.0.0.1:1234/v1",
                    None,
                    "model",
                    "system",
                    "prompt",
                )
        self.assertIn("invalid response", ctx.exception.public_message.lower())

    async def test_gemini_key_is_sent_as_param_not_embedded_in_url(self):
        _FakeAsyncClient.response = _response(
            json_data={
                "candidates": [
                    {"content": {"parts": [{"text": "enhanced"}]}}
                ]
            }
        )
        with patch("app.core.llm.httpx.AsyncClient", _FakeAsyncClient):
            result = await call_llm(
                "gemini",
                "http://127.0.0.1:9000",
                "gemini-secret",
                "model-a",
                "system",
                "prompt",
            )
        self.assertEqual(result, "enhanced")
        _method, url, kwargs = _FakeAsyncClient.calls[0]
        self.assertNotIn("gemini-secret", url)
        self.assertEqual(kwargs.get("params"), {"key": "gemini-secret"})

    async def test_unsupported_provider_is_config_error(self):
        with self.assertRaises(LLMConfigError):
            await call_llm("mystery", None, None, "model", "system", "prompt")


if __name__ == "__main__":
    unittest.main()
