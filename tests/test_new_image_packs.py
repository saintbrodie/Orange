import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import workflow_packs
from app.core.config import get_system_prompt
from app.core.config_validation import validate_config
from app.core.preflight import validate_mappings, validate_workflow_structure
from app.core.workflow_pack_probe import inspect_workflow_pack


class NewImagePackTests(unittest.TestCase):
    def test_packs_are_portable_and_reuse_inventory(self):
        stats = {"system": {"comfyui_version": "0.45.0"}, "devices": [
            {"name": "NVIDIA RTX 5000 Ada", "type": "cuda", "vram_total": 32 * 1024**3},
        ]}
        for pack_id in ("qwen-image-2.1-edit", "moss-image"):
            with self.subTest(pack=pack_id):
                manifest = workflow_packs.get_workflow_pack(pack_id)
                tool = manifest["tool"]
                graph = json.loads((Path(workflow_packs.DEFAULT_WORKFLOWS_DIR) / tool["workflowFile"]).read_text())
                self.assertEqual(validate_config({"tools": [tool]})["errors"], [])
                self.assertEqual(validate_workflow_structure(graph)["errors"], [])
                self.assertEqual(validate_mappings(graph, tool["nodeMapping"])["errors"], [])
                self.assertFalse(any(n["class_type"] in {"TextGenerate", "TextGenerateLTX2Prompt", "ComfySwitchNode"} for n in graph.values()))
                selected = workflow_packs.select_model_dependencies(pack_id, stats)
                self.assertEqual(selected[0]["precision"], "int8")
                self.assertEqual(workflow_packs.select_model_dependencies(pack_id, {})[0]["precision"], "bf16")
                self.assertEqual(len(selected), 3)
                info = {n["class_type"]: {"input": {"required": {}}} for n in graph.values()}
                by_id = {item["id"]: item for item in selected}
                for binding in manifest["bindings"]:
                    node_type = graph[binding["nodeId"]]["class_type"]
                    info[node_type]["input"]["required"][binding["field"]] = [
                        "COMBO", {"options": ["organized/" + by_id[binding["modelId"]]["filename"]]},
                    ]
                inspection = inspect_workflow_pack(pack_id, info, stats)
                self.assertTrue(inspection["ready"])
                self.assertEqual(inspection["recommendedDownloads"], [])
                with tempfile.TemporaryDirectory() as directory:
                    with patch.object(workflow_packs, "ACTIVE_WORKFLOWS_DIR", directory):
                        path = workflow_packs.materialize_workflow_pack(pack_id, inspection["selectedModels"])
                    bound = json.loads(Path(path).read_text())
                for binding in manifest["bindings"]:
                    self.assertEqual(bound[binding["nodeId"]]["inputs"][binding["field"]],
                                     by_id[binding["modelId"]]["filename"])
                # Every node contributes to the saved result; no template previews/refiner loaders remain.
                seen = set()
                def visit(node_id):
                    if node_id in seen:
                        return
                    seen.add(node_id)
                    for value in graph[node_id]["inputs"].values():
                        if isinstance(value, list):
                            visit(value[0])
                visit("9")
                self.assertEqual(seen, set(graph))

    def test_qwen_edit_uses_source_canvas_and_native_conditioning(self):
        manifest = workflow_packs.get_workflow_pack("qwen-image-2.1-edit")
        graph = json.loads((Path(workflow_packs.DEFAULT_WORKFLOWS_DIR) / manifest["workflowFile"]).read_text())
        self.assertEqual(set(manifest["tool"]["nodeMapping"]), {"image", "prompt", "seed"})
        self.assertEqual(graph["5"]["inputs"]["images.image_1"], ["4", 0])
        self.assertEqual(graph["7"]["inputs"]["latent_image"], ["5", 2])
        self.assertEqual(graph["12"]["inputs"]["cfg"], 1)

    def test_qwen_turbo_uses_exact_sigmas_and_texture_fix_vae_in_both_modes(self):
        from app.core.video_controls import tool_variants
        manifest = workflow_packs.get_workflow_pack("qwen-image-2.1-edit")
        diffusion = next(m for m in manifest["models"] if m["id"] == "diffusion")
        self.assertTrue(all("turbo" in v["filename"] for v in diffusion["variants"]))
        vae = next(m for m in manifest["models"] if m["id"] == "vae")
        self.assertIn("madebyollin/texture-fix-vae-for-qwen-image-2.1/resolve/main/", vae["url"])
        for tool in tool_variants(manifest["tool"]):
            graph = json.loads((Path(workflow_packs.DEFAULT_WORKFLOWS_DIR) / tool["workflowFile"]).read_text())
            self.assertEqual(graph["3"]["inputs"]["vae_name"], vae["filename"])
            self.assertEqual(graph["7"]["class_type"], "SamplerCustomAdvanced")
            self.assertEqual(graph["7"]["inputs"]["sigmas"], ["14", 0])
            self.assertEqual(graph["14"]["inputs"]["sigmas"], "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0")
            self.assertEqual(tool["nodeMapping"]["seed"], {"nodeId": "11", "field": "noise_seed", "generateRandom": True})

    def test_moss_preserves_template_sampling_and_aligned_ratios(self):
        manifest = workflow_packs.get_workflow_pack("moss-image")
        graph = json.loads((Path(workflow_packs.DEFAULT_WORKFLOWS_DIR) / manifest["workflowFile"]).read_text())
        self.assertEqual(graph["7"]["inputs"]["sampler_name"], "er_sde")
        self.assertEqual(graph["7"]["inputs"]["steps"], 25)
        self.assertEqual(graph["7"]["inputs"]["cfg"], 2.5)
        self.assertEqual(graph["7"]["inputs"]["model"], ["1", 0])
        for ratio in manifest["tool"]["aspectRatios"].values():
            self.assertEqual(ratio["width"] % 16, 0)
            self.assertEqual(ratio["height"] % 16, 0)

    def test_native_enhancement_has_model_specific_prompts(self):
        for tool_id in ("qwen-image-2-1-edit", "moss-image", "ltx-2-5-video"):
            prompt = get_system_prompt(tool_id)
            self.assertIn({"qwen-image-2-1-edit": "edit instruction", "moss-image": "scene caption", "ltx-2-5-video": "video scene"}[tool_id], prompt)


if __name__ == "__main__":
    unittest.main()
