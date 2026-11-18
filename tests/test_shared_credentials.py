import os
import unittest
from unittest.mock import patch, Mock

from app.core import civitai, huggingface, llm
import httpx
from fastapi import FastAPI
from app.api.media_providers import router


class SharedCredentialsTests(unittest.TestCase):
    def test_anthropic_uses_shared_key(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.core.media_provider_config.credential', return_value='anthropic-secret') as key:
            self.assertEqual(llm.resolve_api_key('anthropic', None), 'anthropic-secret')
            key.assert_called_with('anthropic')

    def test_compatible_provider_never_inherits_cloud_key(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'cloud-secret'}), patch('app.core.media_provider_config.credential') as key:
            self.assertIsNone(llm.resolve_api_key('openai-compatible', None))
            self.assertEqual(llm.resolve_api_key('openai-compatible', 'local-secret'), 'local-secret')
            key.assert_not_called()
    def test_saved_keys_are_used_only_for_official_llm_endpoints(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.core.media_provider_config.credential', return_value='saved-secret') as key:
            self.assertEqual(llm.resolve_api_key('openai', None), 'saved-secret')
            self.assertEqual(llm.resolve_api_key('gemini', None), 'saved-secret')
            self.assertEqual(llm.resolve_api_key('openai', None, 'https://api.openai.com/v1'), 'saved-secret')
            for url in ('http://localhost:11434/v1', 'https://openrouter.ai/api/v1', 'https://api.openai.com.evil.example/v1', 'http://api.openai.com/v1'):
                key.reset_mock()
                self.assertIsNone(llm.resolve_api_key('openai', None, url))
                key.assert_not_called()

    def test_override_and_environment_keep_precedence(self):
        with patch.dict(os.environ, {}, clear=True), patch('app.core.media_provider_config.credential') as key:
            self.assertEqual(llm.resolve_api_key('openai', 'override'), 'override')
            key.assert_not_called()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'environment'}):
            self.assertEqual(llm.resolve_api_key('openai', 'override'), 'environment')

    def test_civitai_environment_status_never_returns_key(self):
        with patch.dict(os.environ, {'CIVITAI_API_KEY': 'environment-secret'}), patch.object(civitai, '_vault', side_effect=OSError()):
            self.assertEqual(civitai.get_token(), 'environment-secret')
            self.assertEqual(civitai.token_status(), {'configured': True, 'saved': False, 'source': 'environment'})

    def test_download_headers_are_scoped_to_civitai(self):
        with patch.object(civitai, 'get_token', return_value='saved-secret') as key:
            self.assertEqual(huggingface.auth_headers('https://civitai.com/api/download/models/123'), {'Authorization': 'Bearer saved-secret'})
            for url in ('http://civitai.com/model', 'https://civitai.com.evil.example/file', 'https://storage.example/file'):
                key.reset_mock()
                self.assertEqual(civitai.auth_headers(url), {})
                key.assert_not_called()

    def test_civitai_native_store_and_validation(self):
        with patch.object(civitai, '_vault') as vault:
            civitai.save_token('valid-secret')
            vault.assert_called_with('set_password', 'valid-secret')
            for value in ('short', 'bad\nsecret', None):
                with self.assertRaises(ValueError): civitai.save_token(value)

    def test_civitai_redirect_cannot_forward_key_to_huggingface(self):
        import urllib.request
        request = urllib.request.Request('https://civitai.com/api/download/models/123')
        request.add_unredirected_header('Authorization', 'Bearer saved-secret')
        redirected = huggingface._HubRedirectHandler().redirect_request(request, None, 302, 'Found', {}, 'https://huggingface.co/a')
        self.assertIsNone(redirected.get_header('Authorization'))


class CredentialRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_openai_fixed_endpoint_and_compatible_ollama_default(self):
        calls = []
        def transport(request):
            calls.append(request)
            return httpx.Response(200, json={'data': [{'id': 'text-model'}]})
        native = httpx.AsyncClient
        def client_factory(**kwargs):
            return native(transport=httpx.MockTransport(transport), **kwargs)
        with patch.dict(os.environ, {}, clear=True), patch('app.core.media_provider_config.credential', return_value='saved-key'), patch.object(llm.httpx, 'AsyncClient', side_effect=client_factory):
            await llm.list_llm_models('openai-cloud', 'https://wrong.example', 'stale-key')
            await llm.list_llm_models('openai-compatible', None, None)
        self.assertEqual(str(calls[0].url), 'https://api.openai.com/v1/models')
        self.assertEqual(calls[0].headers['authorization'], 'Bearer saved-key')
        self.assertEqual(str(calls[1].url), 'http://127.0.0.1:11434/v1/models')
        self.assertNotIn('authorization', calls[1].headers)
    async def test_cloud_model_list_discards_stale_connection_fields(self):
        from app.api import llm_api
        from unittest.mock import AsyncMock
        for provider in ('openai-cloud', 'gemini', 'anthropic', 'openrouter', 'venice', 'xai'):
            with patch.object(llm_api, 'list_llm_models', AsyncMock(return_value=['text-model'])) as listing:
                await llm_api.get_llm_models({'provider': provider, 'baseUrl': 'https://wrong.example', 'apiKey': 'stale-secret'}, _=True)
                self.assertIsNone(listing.call_args.kwargs['base_url'])
                self.assertIsNone(listing.call_args.kwargs['api_key'])

    async def test_anthropic_credential_management_and_test(self):
        from app.core import media_provider_config as config
        from app.api import media_providers
        from unittest.mock import AsyncMock
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.object(config, 'SETTINGS_PATH', Path(directory) / 'providers.json'), patch.object(config, '_vault', return_value='saved-secret'), patch.dict(os.environ, {}, clear=True):
            config.save_provider('anthropic', {'enabled': False, 'apiKey': 'saved-secret'})
            record = next(item for item in config.public_settings() if item['id'] == 'anthropic')
            self.assertTrue(record['configured'])
            self.assertEqual(record['catalog'], [])
            with patch.object(llm, 'list_llm_models', AsyncMock(return_value=['claude-model'])) as listing:
                result = await media_providers.test_provider('anthropic', _=True)
                self.assertEqual(result['status'], 'connected')
                listing.assert_awaited_once()
    async def test_civitai_management_requires_admin(self):
        app = FastAPI(); app.include_router(router)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://orange') as client:
            for method, suffix in [('GET', ''), ('PUT', ''), ('DELETE', ''), ('POST', '/test')]:
                result = await client.request(method, '/api/admin/credentials/civitai' + suffix, json={'apiKey': 'private-secret'})
                self.assertEqual(result.status_code, 401)
                self.assertNotIn('private-secret', result.text)
