import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import httpx
from fastapi import FastAPI

from app.api import workflow_pack_admin
from app.core import config, media_provider_config
from app.core.media_tool_inputs import public_api_inputs


class CuratedApiToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_presets_require_keys_and_add_once_without_comfyui(self):
        app = FastAPI()
        app.include_router(workflow_pack_admin.router)
        keys = {}
        enabled = set()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / 'config.json'
            config_path.write_text('{"adminKey":"test-admin","apiOnly":true,"tools":[],"comfyServers":[]}', encoding='utf-8')
            with mock.patch.object(config, 'USER_CONFIG_PATH', str(config_path)), mock.patch.object(media_provider_config, 'credential', side_effect=lambda provider: keys.get(provider, '')), mock.patch.object(media_provider_config, 'enabled', side_effect=lambda provider, model: provider in enabled):
                self.addCleanup(config.invalidate_config_cache)
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://orange') as client:
                    catalog_url = '/api/admin/workflow-packs'
                    self.assertEqual((await client.post(f'{catalog_url}/api-tools/api-nano-banana')).status_code, 401)
                    client.headers['Authorization'] = 'Bearer test-admin'
                    catalog = (await client.get(catalog_url)).json()
                    self.assertEqual(catalog['servers'], [])
                    packs = {pack['id']: pack for pack in catalog['packs'] if 'api' in pack.get('tags', [])}
                    self.assertEqual(set(packs), {'api-nano-banana', 'api-gpt-image'})
                    self.assertEqual(packs['api-nano-banana']['providerName'], 'Google')
                    self.assertNotEqual(packs['api-nano-banana']['tagline'], packs['api-gpt-image']['tagline'])
                    for pack_id, pack in packs.items():
                        with self.subTest(pack=pack_id):
                            self.assertEqual(pack['thumbnail'], f'/static/curated-thumbnails/{pack_id}.jpg')
                            self.assertTrue(pack['thumbnailAlt'])
                            self.assertTrue((Path(config.PROJECT_ROOT) / pack['thumbnail'].lstrip('/')).is_file())
                            self.assertEqual(pack['setupRequired'], 'key')
                            path = f'{catalog_url}/api-tools/{pack_id}'
                            response = await client.post(path)
                            self.assertEqual(response.status_code, 409)
                            self.assertIn('API key', response.json()['detail'])
                            keys[pack['tool']['provider']] = 'private-test-key'
                            self.assertIn('Enable', (await client.post(path)).json()['detail'])
                            enabled.add(pack['tool']['provider'])
                            response = await client.post(path)
                            self.assertEqual(response.status_code, 200, response.text)
                            self.assertTrue(response.json()['added'])
                            tool = response.json()['tool']
                            self.assertFalse(tool['api']['requireImage'])
                            self.assertEqual(tool['api']['references'], 1)
                            public_inputs = public_api_inputs(tool)
                            self.assertTrue(public_inputs['firstFrame'])
                            self.assertNotIn('image', public_inputs['nodeMapping'])
                            self.assertFalse((await client.post(path)).json()['added'])
                    response = await client.get(catalog_url)
                    self.assertNotIn('private-test-key', response.text)
                    installed = [pack['id'] for pack in response.json()['packs'] if pack['installed']]
                    self.assertCountEqual(installed, packs)
                    self.assertEqual(len(config.load_config()['tools']), 2)


class WorkflowPackAdminTests(unittest.TestCase):
    def test_active_tool_resolves_stale_model_subfolder_without_changing_workflow(self):
        workflow = {"58": {"class_type": "VAELoader", "inputs": {"vae_name": "Wan\\wan_2.1_vae.safetensors"}}}
        info = {"VAELoader": {"input": {"required": {"vae_name": [["wan_2.1_vae.safetensors"]]}}}}
        tool = {"workflowFile": "krea.json", "nodeMapping": {}}
        with mock.patch.object(workflow_pack_admin, "get_base_workflow", return_value=workflow):
            result = workflow_pack_admin._inspect_active_tool(tool, info)
            self.assertTrue(result["activeWorkflowReady"])
            self.assertEqual(workflow["58"]["inputs"]["vae_name"], "Wan\\wan_2.1_vae.safetensors")
            workflow["58"]["inputs"]["vae_name"] = "wan_2.1_vae.safetensors"
            self.assertTrue(workflow_pack_admin._inspect_active_tool(tool, info)["activeWorkflowReady"])

    def test_active_tool_checks_alternate_workflow_and_missing_files(self):
        tool = {"workflowFile": "base.json", "nodeMapping": {}, "referenceVariant": {"workflowFile": "reference.json", "nodeMapping": {}}}
        workflow = {"1": {"class_type": "VAELoader", "inputs": {"vae_name": "model.safetensors"}}}
        info = {"VAELoader": {"input": {"required": {"vae_name": [["model.safetensors"]]}}}}
        with mock.patch.object(workflow_pack_admin, "get_base_workflow", side_effect=[workflow, FileNotFoundError("Missing alternate workflow")]):
            result = workflow_pack_admin._inspect_active_tool(tool, info)
        self.assertFalse(result["activeWorkflowReady"])
        self.assertEqual(result["activeWorkflowIssues"][0]["workflowFile"], "reference.json")

    def test_server_lookup_normalizes_trailing_slash(self):
        config = {"comfyServers": [{"url": "http://127.0.0.1:8188/", "priority": 2}]}
        index, server = workflow_pack_admin._server_for_url(config, "http://127.0.0.1:8188")
        self.assertEqual(index, 0)
        self.assertEqual(server["priority"], 2)

    def test_catalog_marks_tools_already_in_config(self):
        packs = [
            {"id": "z-image-turbo", "tool": {"id": "z-image"}},
            {"id": "krea-2-turbo", "tool": {"id": "krea-2"}},
        ]
        config = {
            "tools": [{"id": "z-image"}],
            "comfyServers": [{"url": "http://127.0.0.1:8188", "priority": 1, "modelsRoot": "/models"}],
        }
        with mock.patch.object(workflow_pack_admin, "load_config", return_value=config), mock.patch.object(
            workflow_pack_admin, "list_workflow_packs", return_value=packs
        ), mock.patch.object(workflow_pack_admin, "resolve_models_root", return_value="/detected"):
            result = workflow_pack_admin.get_workflow_pack_catalog(_=True)

        by_id = {pack["id"]: pack for pack in result["packs"]}
        self.assertTrue(by_id["z-image-turbo"]["installed"])
        self.assertFalse(by_id["krea-2-turbo"]["installed"])
        self.assertEqual(result["servers"][0]["modelsRoot"], "/models")

    def test_install_adds_tool_only_after_routable_preflight(self):
        config = {
            "adminKey": "secret-password",
            "tools": [],
            "comfyServers": [{"url": "http://127.0.0.1:8188", "priority": 1}],
        }
        manifest = {
            "id": "krea-2-turbo",
            "workflowFile": "image_krea2_turbo_t2i_int8.json",
            "tool": {"id": "krea-2", "name": "Krea 2 Turbo", "nodeMapping": {"prompt": {"nodeId": "52", "field": "text"}}},
        }
        selected_model = {
            "id": "diffusion",
            "folder": "diffusion_models",
            "filename": "krea2_turbo_int8_convrot.safetensors",
            "precision": "int8",
            "url": "https://example.test/krea.safetensors",
        }
        inspection = {
            "ready": False,
            "selectedModels": [],
            "missingModels": [{"id": "diffusion"}],
            "missingNodes": [],
            "unknownModels": [],
            "recommendedDownloads": [selected_model],
        }
        install_result = {
            "failures": [],
            "selectedModels": [selected_model],
            "installed": ["/models/diffusion_models/krea2_turbo_int8_convrot.safetensors"],
            "skipped": [],
        }
        preflight = {"backends": [{"reachable": True, "errors": [], "warnings": []}], "summary": {"status": "ready"}}
        updated_config = {**config, "tools": [manifest["tool"]]}

        async def run_test():
            with mock.patch.object(workflow_pack_admin, "get_workflow_pack", return_value=manifest), mock.patch.object(
                workflow_pack_admin, "load_config", return_value=config
            ), mock.patch.object(workflow_pack_admin, "resolve_models_root", return_value="/models"), mock.patch.object(
                workflow_pack_admin, "_backend_metadata", new=mock.AsyncMock(return_value=({}, {"devices": []}))
            ), mock.patch.object(workflow_pack_admin, "inspect_workflow_pack", return_value=inspection), mock.patch.object(
                workflow_pack_admin, "install_workflow_pack", return_value=install_result
            ), mock.patch.object(
                workflow_pack_admin, "get_base_workflow", return_value={"52": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
            ), mock.patch.object(workflow_pack_admin, "run_preflight", new=mock.AsyncMock(return_value=preflight)), mock.patch.object(
                workflow_pack_admin, "workflow_compatibility_key", return_value="key"
            ), mock.patch.object(workflow_pack_admin, "add_pack_tool_to_config", return_value=updated_config), mock.patch.object(
                workflow_pack_admin, "save_config"
            ) as save_config, mock.patch.object(workflow_pack_admin.backend_manager, "record_preflight"), mock.patch.object(
                workflow_pack_admin.backend_manager, "refresh_all", new=mock.AsyncMock()
            ):
                result = await workflow_pack_admin.install_admin_workflow_pack(
                    {"packId": "krea-2-turbo", "serverUrl": "http://127.0.0.1:8188", "modelsRoot": "/models"},
                    _=True,
                )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["selectedModels"][0]["precision"], "int8")
            saved = save_config.call_args.args[0]
            self.assertEqual(saved["comfyServers"][0]["modelsRoot"], "/models")

        asyncio.run(run_test())

    def test_activate_uses_existing_models_without_models_root(self):
        config = {
            "adminKey": "secret-password",
            "tools": [],
            "comfyServers": [{"url": "http://remote:8188", "priority": 1}],
        }
        manifest = {
            "id": "z-image-turbo",
            "workflowFile": "image_z_image_turbo.json",
            "tool": {"id": "z-image", "name": "Generate Image", "nodeMapping": {}},
        }
        inspection = {
            "ready": True,
            "selectedModels": [{"id": "diffusion", "filename": "existing/z.safetensors", "reuseExisting": True}],
            "missingModels": [],
            "missingNodes": [],
            "unknownModels": [],
            "recommendedDownloads": [],
        }
        preflight = {"backends": [{"reachable": True, "errors": [], "warnings": []}], "summary": {"status": "ready"}}
        updated_config = {**config, "tools": [manifest["tool"]]}

        async def run_test():
            with mock.patch.object(workflow_pack_admin, "get_workflow_pack", return_value=manifest), mock.patch.object(
                workflow_pack_admin, "load_config", return_value=config
            ), mock.patch.object(
                workflow_pack_admin, "_backend_metadata", new=mock.AsyncMock(return_value=({}, {"devices": []}))
            ), mock.patch.object(workflow_pack_admin, "inspect_workflow_pack", return_value=inspection), mock.patch.object(
                workflow_pack_admin, "materialize_workflow_pack"
            ) as materialize, mock.patch.object(
                workflow_pack_admin, "get_base_workflow", return_value={}
            ), mock.patch.object(workflow_pack_admin, "run_preflight", new=mock.AsyncMock(return_value=preflight)), mock.patch.object(
                workflow_pack_admin, "workflow_compatibility_key", return_value="key"
            ), mock.patch.object(workflow_pack_admin, "add_pack_tool_to_config", return_value=updated_config), mock.patch.object(
                workflow_pack_admin, "save_config"
            ), mock.patch.object(workflow_pack_admin.backend_manager, "record_preflight"), mock.patch.object(
                workflow_pack_admin.backend_manager, "refresh_all", new=mock.AsyncMock()
            ):
                result = await workflow_pack_admin.activate_admin_workflow_pack(
                    {"packId": "z-image-turbo", "serverUrl": "http://remote:8188"},
                    _=True,
                )

            self.assertEqual(result["mode"], "existing")
            materialize.assert_called_once_with("z-image-turbo", inspection["selectedModels"])

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
