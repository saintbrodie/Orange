import json
import unittest
from pathlib import Path

from app.core import workflow_pack_probe


class WorkflowPackProbeTests(unittest.TestCase):
    def _z_object_info(self, include_vae=True):
        root = Path(__file__).resolve().parents[1]
        workflow = json.loads((root / "workflows" / "defaults" / "image_z_image_turbo.json").read_text())
        object_info = {
            node["class_type"]: {"input": {"required": {}}}
            for node in workflow.values()
            if isinstance(node, dict) and node.get("class_type")
        }
        object_info["UNETLoader"]["input"]["required"]["unet_name"] = [[
            "organized/z_image_turbo_bf16.safetensors"
        ]]
        object_info["CLIPLoader"]["input"]["required"]["clip_name"] = [[
            "encoders/qwen_3_4b.safetensors"
        ]]
        object_info["VAELoader"]["input"]["required"]["vae_name"] = [[
            "ae.safetensors"
        ] if include_vae else ["other_vae.safetensors"]]
        return object_info

    def _modern_nvidia(self):
        return {
            "system": {"comfyui_version": "0.34.0", "pytorch_version": "2.14.0+cu130"},
            "devices": [{"name": "NVIDIA RTX 5000 Ada", "type": "cuda", "vram_total": 24 * 1024**3}],
        }

    def test_existing_bf16_variant_is_ready_even_when_int8_is_preferred(self):
        inspection = workflow_pack_probe.inspect_workflow_pack(
            "z-image-turbo",
            self._z_object_info(),
            self._modern_nvidia(),
        )
        self.assertTrue(inspection["ready"])
        selected = {item["id"]: item for item in inspection["selectedModels"]}
        self.assertEqual(selected["diffusion"]["filename"], "organized/z_image_turbo_bf16.safetensors")
        self.assertEqual(selected["diffusion"]["precision"], "bf16")
        self.assertTrue(selected["diffusion"]["reuseExisting"])
        self.assertEqual(selected["text_encoder"]["filename"], "encoders/qwen_3_4b.safetensors")

    def test_missing_dependency_reports_only_the_missing_download(self):
        inspection = workflow_pack_probe.inspect_workflow_pack(
            "z-image-turbo",
            self._z_object_info(include_vae=False),
            self._modern_nvidia(),
        )
        self.assertFalse(inspection["ready"])
        self.assertEqual([item["id"] for item in inspection["missingModels"]], ["vae"])
        self.assertEqual([item["filename"] for item in inspection["recommendedDownloads"]], ["ae.safetensors"])

        selection = workflow_pack_probe.selection_for_install(inspection)
        by_id = {item["id"]: item for item in selection}
        self.assertTrue(by_id["diffusion"]["reuseExisting"])
        self.assertTrue(by_id["text_encoder"]["reuseExisting"])
        self.assertEqual(by_id["vae"]["filename"], "ae.safetensors")
        self.assertFalse(by_id["vae"].get("reuseExisting", False))


if __name__ == "__main__":
    unittest.main()
