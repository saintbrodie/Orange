import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import workflow_packs


class WorkflowPackTests(unittest.TestCase):
    def test_curated_pack_catalog_contains_recommended_and_optional_tools(self):
        packs = {pack["id"]: pack for pack in workflow_packs.list_workflow_packs()}
        self.assertEqual(
            set(packs),
            {"z-image-turbo", "krea-2-turbo", "klein-9b-edit", "seedvr2-7b-upscale"},
        )
        self.assertTrue(packs["z-image-turbo"]["recommended"])
        self.assertFalse(packs["krea-2-turbo"]["recommended"])

    def test_default_z_image_workflow_uses_no_lora(self):
        root = Path(__file__).resolve().parents[1]
        workflow = json.loads((root / "workflows" / "defaults" / "image_z_image_turbo.json").read_text())
        class_types = {node.get("class_type") for node in workflow.values()}

        self.assertNotIn("LoraLoaderModelOnly", class_types)
        self.assertEqual(workflow["69"]["inputs"]["model"], ["66", 0])

    def test_fresh_default_config_requires_no_curated_tool(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "workflows" / "defaults" / "workflows-config.json").read_text())
        self.assertEqual(config["tools"], [])

    def test_krea_pack_preserves_wan_vae_choice(self):
        manifest = workflow_packs.get_workflow_pack("krea-2-turbo")
        vae = next(model for model in manifest["models"] if model["id"] == "vae")
        self.assertEqual(vae["filename"], "wan_2.1_vae.safetensors")
        self.assertIn("Comfy-Org/Wan_2.1_ComfyUI_repackaged", vae["url"])

    def test_seedvr2_workflow_uses_native_nodes(self):
        root = Path(__file__).resolve().parents[1]
        workflow = json.loads(
            (root / "workflows" / "defaults" / "utility_seedvr2_7b_int8_upscale_image.json").read_text()
        )
        class_types = {node.get("class_type") for node in workflow.values()}
        self.assertIn("SeedVR2Preprocess", class_types)
        self.assertIn("SeedVR2Conditioning", class_types)
        self.assertIn("SeedVR2PostProcessing", class_types)

    def test_modern_nvidia_prefers_int8_convrot(self):
        stats = {
            "system": {"comfyui_version": "0.34.0", "pytorch_version": "2.14.0+cu130"},
            "devices": [{"name": "NVIDIA GeForce RTX 4090", "type": "cuda", "vram_total": 24 * 1024**3}],
        }
        selected = {item["id"]: item for item in workflow_packs.select_model_dependencies("krea-2-turbo", stats)}
        self.assertEqual(selected["diffusion"]["precision"], "int8")
        self.assertEqual(selected["text_encoder"]["precision"], "fp8")

    def test_rocm_falls_back_to_fp8(self):
        stats = {
            "system": {"comfyui_version": "0.34.0", "pytorch_version": "2.9.1+rocm7.2"},
            "devices": [{"name": "AMD Radeon RX 9070 XT", "type": "rocm", "vram_total": 16 * 1024**3}],
        }
        selected = {item["id"]: item for item in workflow_packs.select_model_dependencies("krea-2-turbo", stats)}
        self.assertEqual(selected["diffusion"]["precision"], "fp8")
        self.assertEqual(selected["text_encoder"]["precision"], "fp8")

    def test_high_vram_non_int8_backend_can_choose_bf16(self):
        stats = {
            "system": {"comfyui_version": "0.34.0"},
            "devices": [{"name": "Large accelerator", "type": "mps", "vram_total": 64 * 1024**3}],
        }
        selected = {item["id"]: item for item in workflow_packs.select_model_dependencies("krea-2-turbo", stats)}
        self.assertEqual(selected["diffusion"]["precision"], "bf16")
        self.assertEqual(selected["text_encoder"]["precision"], "bf16")

    def test_models_root_prefers_explicit_or_managed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit = os.path.join(tmp, "explicit")
            os.mkdir(explicit)
            managed = os.path.join(tmp, "ComfyUI")
            managed_models = os.path.join(managed, "models")
            os.makedirs(managed_models)

            with mock.patch.dict(os.environ, {"ORANGE_COMFYUI_DIR": managed}, clear=False):
                self.assertEqual(workflow_packs.resolve_models_root(explicit), os.path.abspath(explicit))
                self.assertEqual(workflow_packs.resolve_models_root(), os.path.abspath(managed_models))

    def test_pack_installer_skips_existing_files_and_downloads_selected_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_root = Path(tmp) / "models"
            models_root.mkdir()
            existing = models_root / "vae" / "ae.safetensors"
            existing.parent.mkdir()
            existing.write_bytes(b"already here")
            downloaded = []

            def fake_download(url, destination):
                Path(destination).write_bytes(b"downloaded")
                downloaded.append(Path(destination).name)

            with mock.patch.object(workflow_packs, "_download_file", side_effect=fake_download):
                result = workflow_packs.install_workflow_pack("z-image-turbo", str(models_root))

            self.assertEqual(result["failures"], [])
            self.assertIn(existing.as_posix(), [Path(path).as_posix() for path in result["skipped"]])
            self.assertEqual(
                set(downloaded),
                {"z_image_turbo_bf16.safetensors", "qwen_3_4b_fp8_mixed.safetensors"},
            )

    def test_pack_installer_reuses_inventory_model_without_downloading_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_root = Path(tmp) / "models"
            models_root.mkdir()
            selected = [
                {
                    "id": "diffusion",
                    "folder": "diffusion_models",
                    "filename": "organized/z_image_turbo_bf16.safetensors",
                    "precision": "bf16",
                    "url": "https://example.test/z.safetensors",
                    "reuseExisting": True,
                },
                {
                    "id": "vae",
                    "folder": "vae",
                    "filename": "ae.safetensors",
                    "precision": "bf16",
                    "url": "https://example.test/ae.safetensors",
                },
            ]
            downloaded = []

            def fake_download(url, destination):
                Path(destination).write_bytes(b"downloaded")
                downloaded.append(Path(destination).name)

            with mock.patch.object(workflow_packs, "_download_file", side_effect=fake_download):
                result = workflow_packs.install_workflow_pack(
                    "z-image-turbo",
                    str(models_root),
                    selected_models=selected,
                )

            self.assertEqual(downloaded, ["ae.safetensors"])
            self.assertIn("organized/z_image_turbo_bf16.safetensors", result["skipped"])

    def test_materialize_workflow_binds_selected_model_filenames(self):
        stats = {
            "system": {"comfyui_version": "0.34.0"},
            "devices": [{"name": "NVIDIA RTX 5000 Ada", "type": "cuda", "vram_total": 32 * 1024**3}],
        }
        selected = workflow_packs.select_model_dependencies("z-image-turbo", stats)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(workflow_packs, "ACTIVE_WORKFLOWS_DIR", tmp):
                path = workflow_packs.materialize_workflow_pack("z-image-turbo", selected)
            workflow = json.loads(Path(path).read_text())

        self.assertEqual(workflow["66"]["inputs"]["unet_name"], "z_image_turbo_int8_convrot.safetensors")
        self.assertEqual(workflow["62"]["inputs"]["clip_name"], "qwen_3_4b.safetensors")

    def test_add_pack_tool_to_config_is_idempotent(self):
        config = {"tools": [{"id": "z-image"}]}
        updated = workflow_packs.add_pack_tool_to_config(config, "krea-2-turbo")
        updated = workflow_packs.add_pack_tool_to_config(updated, "krea-2-turbo")
        self.assertEqual([tool["id"] for tool in updated["tools"]].count("krea-2"), 1)


if __name__ == "__main__":
    unittest.main()
