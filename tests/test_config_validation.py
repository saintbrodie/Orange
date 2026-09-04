import copy
import json
import os
import unittest

from app.core.config import DEFAULT_CONFIG_PATH, get_base_workflow
from app.core.config_validation import validate_config


class ConfigValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as handle:
            cls.default_config = json.load(handle)

    def test_default_config_is_valid(self):
        result = validate_config(copy.deepcopy(self.default_config))
        self.assertEqual(result["errors"], [])

    def test_duplicate_tool_ids_are_rejected(self):
        config = copy.deepcopy(self.default_config)
        config["tools"][1]["id"] = config["tools"][0]["id"]

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "tool_id_duplicate" for issue in result["errors"]))

    def test_unknown_mapping_type_is_rejected(self):
        config = copy.deepcopy(self.default_config)
        config["tools"][0]["nodeMapping"]["cfg"] = {"nodeId": "1", "field": "cfg"}

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "mapping_type_unknown" for issue in result["errors"]))

    def test_resolution_mapping_requires_width_and_height(self):
        config = copy.deepcopy(self.default_config)
        del config["tools"][0]["nodeMapping"]["height"]

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "resolution_mapping_incomplete" for issue in result["errors"]))

    def test_bad_backend_url_is_rejected(self):
        config = copy.deepcopy(self.default_config)
        config["comfyServers"][0]["url"] = "not-a-url"

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "server_url_invalid" for issue in result["errors"]))

    def test_missing_mapping_node_is_rejected_locally(self):
        config = copy.deepcopy(self.default_config)
        config["tools"][0]["nodeMapping"]["prompt"]["nodeId"] = "999999"

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "mapping_node_missing" for issue in result["errors"]))

    def test_workflow_path_traversal_is_rejected(self):
        config = copy.deepcopy(self.default_config)
        config["tools"][0]["workflowFile"] = "../secret.json"

        result = validate_config(config)

        self.assertTrue(any(issue["code"] == "workflow_path_invalid" for issue in result["errors"]))

    def test_get_base_workflow_rejects_paths(self):
        with self.assertRaises(FileNotFoundError):
            get_base_workflow(os.path.join("..", "secret.json"))


if __name__ == "__main__":
    unittest.main()
