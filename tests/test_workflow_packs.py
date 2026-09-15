import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import workflow_packs


class WorkflowPackTests(unittest.TestCase):
    def test_z_image_pack_declares_minimal_dependencies(self):
        manifest = workflow_packs.get_workflow_pack("z-image-turbo")
        models = manifest["models"]

        self.assertTrue(manifest["recommended"])
        self.assertEqual({model["folder"] for model in models}, {"diffusion_models", "text_encoders", "vae"})
        self.assertEqual(
            {model["filename"] for model in models},
            {"z_image_turbo_bf16.safetensors", "qwen_3_4b.safetensors", "ae.safetensors"},
        )

    def test_default_z_image_workflow_uses_no_lora(self):
        root = Path(__file__).resolve().parents[1]
        workflow = json.loads((root / "workflows" / "defaults" / "image_z_image_turbo.json").read_text())
        class_types = {node.get("class_type") for node in workflow.values()}

        self.assertNotIn("LoraLoaderModelOnly", class_types)
        self.assertEqual(workflow["69"]["inputs"]["model"], ["66", 0])

    def test_fresh_default_config_only_exposes_starter_tool(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / "workflows" / "defaults" / "workflows-config.json").read_text())

        self.assertEqual([tool["id"] for tool in config["tools"]], ["z-image"])
        self.assertEqual(config["tools"][0]["workflowFile"], "image_z_image_turbo.json")

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

    def test_pack_installer_skips_existing_files_and_downloads_missing(self):
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
            self.assertEqual(set(downloaded), {"z_image_turbo_bf16.safetensors", "qwen_3_4b.safetensors"})


if __name__ == "__main__":
    unittest.main()
