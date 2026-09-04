import unittest

from app.core.preflight import validate_backend, validate_mappings, validate_workflow_structure


def _workflow():
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "model.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "hello", "clip": ["1", 1]},
        },
    }


def _object_info():
    return {
        "CheckpointLoaderSimple": {
            "input": {
                "required": {
                    "ckpt_name": [["model.safetensors", "other.safetensors"]],
                }
            }
        },
        "CLIPTextEncode": {
            "input": {
                "required": {
                    "text": ["STRING", {"multiline": True}],
                    "clip": ["CLIP"],
                }
            }
        },
    }


class WorkflowPreflightTests(unittest.TestCase):
    def test_ui_workflow_format_is_rejected(self):
        result = validate_workflow_structure({"nodes": [], "links": []})
        self.assertTrue(result["errors"])
        self.assertEqual(result["errors"][0]["code"], "workflow_ui_format")

    def test_mapping_to_missing_node_is_error(self):
        result = validate_mappings(
            _workflow(),
            {"prompt": {"nodeId": "999", "field": "text"}},
        )
        self.assertTrue(any(issue["code"] == "mapping_node_missing" for issue in result["errors"]))

    def test_valid_backend_and_mapping_are_ready(self):
        result = validate_backend(
            _workflow(),
            {"prompt": {"nodeId": "2", "field": "text"}},
            _object_info(),
        )
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_missing_custom_node_is_error(self):
        info = _object_info()
        del info["CLIPTextEncode"]
        result = validate_backend(_workflow(), {}, info)
        self.assertTrue(any(issue["code"] == "node_class_missing" for issue in result["errors"]))

    def test_mapped_field_missing_from_backend_is_error(self):
        result = validate_backend(
            _workflow(),
            {"prompt": {"nodeId": "2", "field": "does_not_exist"}},
            _object_info(),
        )
        self.assertTrue(any(issue["code"] == "mapped_field_missing" for issue in result["errors"]))

    def test_unavailable_model_value_is_warning(self):
        workflow = _workflow()
        workflow["1"]["inputs"]["ckpt_name"] = "missing-model.safetensors"
        result = validate_backend(workflow, {}, _object_info())
        warnings = [issue for issue in result["warnings"] if issue["code"] == "value_unavailable"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["field"], "ckpt_name")

    def test_mapped_required_field_can_be_injected_by_orange(self):
        workflow = _workflow()
        del workflow["2"]["inputs"]["text"]
        result = validate_backend(
            workflow,
            {"prompt": {"nodeId": "2", "field": "text"}},
            _object_info(),
        )
        self.assertFalse(any(issue["code"] == "required_input_missing" for issue in result["errors"]))

    def test_output_text_mapping_is_not_treated_as_node_input(self):
        mapping = {"outputText": {"nodeId": "2", "field": "text_output"}}
        local = validate_mappings(_workflow(), mapping)
        backend = validate_backend(_workflow(), mapping, _object_info())

        self.assertFalse(any(issue["code"] == "mapping_field_not_in_workflow" for issue in local["warnings"]))
        self.assertFalse(any(issue["code"] == "mapped_field_missing" for issue in backend["errors"]))


if __name__ == "__main__":
    unittest.main()
