import asyncio
import unittest
from unittest import mock

from app.api import workflow_pack_admin


class WorkflowPackAdminTests(unittest.TestCase):
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
