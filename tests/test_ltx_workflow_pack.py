import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import workflow_packs
from app.core.config_validation import validate_config
from app.core.workflow_pack_probe import inspect_workflow_pack
from app.core.preflight import validate_mappings, validate_workflow_structure


class LTXWorkflowPackTests(unittest.TestCase):
    def setUp(self):
        self.manifest = workflow_packs.get_workflow_pack("ltx-2.5-t2v")
        self.tool = self.manifest["tool"]
        path = Path(workflow_packs.DEFAULT_WORKFLOWS_DIR) / self.tool["workflowFile"]
        self.workflow = json.loads(path.read_text())

    def test_pack_registers_a_valid_video_tool(self):
        self.assertEqual(self.tool["outputType"], "video")
        self.assertNotIn("image", self.tool["nodeMapping"])
        self.assertEqual(validate_workflow_structure(self.workflow)["errors"], [])
        self.assertEqual(validate_mappings(self.workflow, self.tool["nodeMapping"])["errors"], [])
        self.assertEqual(validate_config({"tools": [self.tool]})["errors"], [])

    def test_av_timing_and_native_output_are_connected(self):
        self.assertEqual(self.workflow["405:356"]["inputs"]["length"], ["video_frames", 0])
        self.assertEqual(self.workflow["video_frames"]["inputs"]["value"], 97)
        self.assertEqual(self.workflow["405:366"]["inputs"]["frames_number"], ["video_frames", 0])
        self.assertEqual(self.workflow["405:366"]["inputs"]["frame_rate"], 24)
        self.assertEqual(self.workflow["405:370"]["inputs"]["fps"], 24)
        self.assertIn("audio", self.workflow["405:370"]["inputs"])
        self.assertEqual(self.workflow["75"]["class_type"], "SaveVideo")
        seen = set()
        def visit(node_id):
            if node_id in seen:
                return
            seen.add(node_id)
            for value in self.workflow[node_id]["inputs"].values():
                if isinstance(value, list):
                    self.assertIn(value[0], self.workflow)
                    visit(value[0])
        visit("75")
        self.assertEqual(seen, set(self.workflow))
        self.assertFalse(any(n["class_type"] == "TextGenerateLTX2Prompt" for n in self.workflow.values()))

    def test_nvidia_uses_int8_and_other_hardware_uses_bf16(self):
        stats = {"system": {"comfyui_version": "0.42.5"}, "devices": [{
            "name": "NVIDIA RTX 5000 Ada", "type": "cuda", "vram_total": 32 * 1024**3,
        }]}
        selected = {m["id"]: m for m in workflow_packs.select_model_dependencies("ltx-2.5-t2v", stats)}
        self.assertEqual(selected["diffusion"]["precision"], "int8")
        self.assertEqual(selected["text_encoder"]["precision"], "int8")
        fallback = {m["id"]: m for m in workflow_packs.select_model_dependencies("ltx-2.5-t2v", {})}
        self.assertEqual(fallback["diffusion"]["precision"], "bf16")
        self.assertEqual(fallback["text_encoder"]["precision"], "bf16")
        self.assertEqual(selected["spatial_upscaler"]["folder"], "latent_upscale_models")

    def test_probe_reuses_native_typed_combo_upscaler_inventory(self):
        image_workflow = json.loads((Path(workflow_packs.DEFAULT_WORKFLOWS_DIR) / self.tool["imageVariant"]["workflowFile"]).read_text())
        info = {n["class_type"]: {"input": {"required": {}}} for graph in (self.workflow, image_workflow) for n in graph.values()}
        models = {m["id"]: m for m in workflow_packs.select_model_dependencies("ltx-2.5-t2v", {})}
        for binding in self.manifest["bindings"]:
            node_type = self.workflow[binding["nodeId"]]["class_type"]
            fields = info[node_type]["input"]["required"]
            spec = fields.setdefault(binding["field"], ["COMBO", {"options": []}])
            spec[1]["options"].append(models[binding["modelId"]]["filename"])
        inspection = inspect_workflow_pack("ltx-2.5-t2v", info, {})
        self.assertTrue(inspection["ready"])
        self.assertEqual(len(inspection["selectedModels"]), 5)
        self.assertEqual(inspection["recommendedDownloads"], [])
        self.assertEqual(inspection["unknownModels"], [])
        del info["LTXVImgToVideoInplace"]
        inspection = inspect_workflow_pack("ltx-2.5-t2v", info, {})
        self.assertFalse(inspection["ready"])
        self.assertIn("LTXVImgToVideoInplace", inspection["missingNodes"])

    def test_install_binds_all_five_components_to_inventory_filenames(self):
        selected = workflow_packs.select_model_dependencies("ltx-2.5-t2v", {})
        for model in selected:
            model["filename"] = "organized/" + model["filename"]
        by_id = {model["id"]: model for model in selected}
        self.assertEqual(len(by_id), 5)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(workflow_packs, "ACTIVE_WORKFLOWS_DIR", directory):
                path = workflow_packs.materialize_workflow_pack("ltx-2.5-t2v", selected)
            workflow = json.loads(Path(path).read_text())
            image_workflow = json.loads((Path(directory) / self.tool["imageVariant"]["workflowFile"]).read_text())
            for binding in self.manifest["bindings"]:
                self.assertEqual(workflow[binding["nodeId"]]["inputs"][binding["field"]],
                                 by_id[binding["modelId"]]["filename"])
                self.assertEqual(image_workflow[binding["nodeId"]]["inputs"][binding["field"]],
                                 by_id[binding["modelId"]]["filename"])


if __name__ == "__main__":
    unittest.main()
