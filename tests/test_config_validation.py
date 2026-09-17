import copy
import json
import os
import unittest

from app.core.config import DEFAULT_CONFIG_PATH, _normalize_curated_tool_defaults, get_base_workflow
from app.core.config_validation import validate_config


class ConfigValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as handle:
            cls.default_config = json.load(handle)

    def config_with_tool(self):
        config = copy.deepcopy(self.default_config)
        config["tools"] = [
            {
                "id": "z-image",
                "name": "Generate Image",
                "workflowFile": "image_z_image_turbo.json",
                "nodeMapping": {
                    "prompt": {"nodeId": "67", "field": "text"},
                    "width": {"nodeId": "68", "field": "width"},
                    "height": {"nodeId": "68", "field": "height"},
                    "seed": {"nodeId": "70", "field": "seed", "generateRandom": True},
                },
            }
        ]
        return config

    def test_default_config_is_valid(self):
        result = validate_config(copy.deepcopy(self.default_config))
        self.assertEqual(result["errors"], [])

    def test_curated_defaults_migrate_legacy_names_order_and_modify_tool(self):
        config = {
            "tools": [
                {"id": "krea-2", "name": "Krea 2 Turbo"},
                {"id": "klein-edit", "name": "Modify Image"},
                {"id": "z-image", "name": "Generate Image"},
            ]
        }
        normalized = _normalize_curated_tool_defaults(config)

        self.assertEqual([tool["id"] for tool in normalized["tools"]], ["z-image", "krea-2", "klein-edit"])
        self.assertEqual(normalized["tools"][0]["name"], "Realistic Generation")
        self.assertEqual(normalized["tools"][1]["name"], "Detailed Generation")
        self.assertEqual(normalized["modifyTool"], "klein-edit")

    def test_curated_defaults_preserve_custom_names_and_modify_choice(self):
        config = {
            "tools": [
                {"id": "z-image", "name": "My Generator"},
                {"id": "klein-edit", "name": "My Editor"},
                {"id": "custom-edit", "name": "Other Editor"},
            ],
            "modifyTool": "custom-edit",
        }
        normalized = _normalize_curated_tool_defaults(config)

        self.assertEqual(normalized["tools"][0]["name"], "My Generator")
        self.assertEqual(normalized["modifyTool"], "custom-edit")

    def test_duplicate_tool_ids_are_rejected(self):
        config = self.config_with_tool()
        duplicate = copy.deepcopy(config["tools"][0])
        config["tools"].append(duplicate)

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "tool_id_duplicate" for issue in result["errors"]))

    def test_unknown_mapping_type_is_rejected(self):
        config = self.config_with_tool()
        config["tools"][0]["nodeMapping"]["cfg"] = {"nodeId": "1", "field": "cfg"}

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "mapping_type_unknown" for issue in result["errors"]))

    def test_resolution_mapping_requires_width_and_height(self):
        config = self.config_with_tool()
        del config["tools"][0]["nodeMapping"]["height"]

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "resolution_mapping_incomplete" for issue in result["errors"]))

    def test_bad_backend_url_is_rejected(self):
        config = copy.deepcopy(self.default_config)
        config["comfyServers"][0]["url"] = "not-a-url"

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "server_url_invalid" for issue in result["errors"]))

    def test_missing_mapping_node_is_rejected_locally(self):
        config = self.config_with_tool()
        config["tools"][0]["nodeMapping"]["prompt"]["nodeId"] = "999999"

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "mapping_node_missing" for issue in result["errors"]))

    def test_workflow_path_traversal_is_rejected(self):
        config = self.config_with_tool()
        config["tools"][0]["workflowFile"] = "../secret.json"

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "workflow_path_invalid" for issue in result["errors"]))

    def test_get_base_workflow_rejects_paths(self):
        with self.assertRaises(FileNotFoundError):
            get_base_workflow(os.path.join("..", "secret.json"))


if __name__ == "__main__":
    unittest.main()
