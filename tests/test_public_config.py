import unittest

from app.core.public_config import build_public_config


class PublicConfigTests(unittest.TestCase):
    def test_admin_and_backend_fields_are_not_exposed(self):
        config = {
            "adminKey": "secret",
            "comfyServers": [{"url": "http://secret-backend:8188"}],
            "llm": {"enabled": True, "apiKey": "sk-secret", "provider": "openai", "model": "private-model"},
            "aspectRatios": {"1:1": {"width": 1024, "height": 1024}},
            "modifyTool": "edit",
            "tools": [
                {
                    "id": "edit",
                    "name": "Edit",
                    "workflowFile": "private-workflow.json",
                    "outputType": "image",
                    "nodeMapping": {
                        "prompt": {"nodeId": "1", "field": "text"},
                        "image": {"nodeId": "2", "field": "image"},
                        "internalThing": {"nodeId": "99", "field": "secret"},
                    },
                    "promptEnhance": {
                        "enabled": True,
                        "apiKey": "tool-secret",
                        "provider": "openai",
                        "model": "hidden-model",
                    },
                    "backendOnly": "nope",
                }
            ],
        }

        public = build_public_config(config)
        serialized = repr(public)
        self.assertNotIn("secret-backend", serialized)
        self.assertNotIn("sk-secret", serialized)
        self.assertNotIn("private-workflow", serialized)
        self.assertNotIn("tool-secret", serialized)
        self.assertNotIn("internalThing", serialized)
        self.assertNotIn("backendOnly", serialized)
        self.assertTrue(public["llmEnabled"])
        self.assertEqual(public["modifyTool"], "edit")
        self.assertEqual(public["tools"][0]["promptEnhance"], {"enabled": True})
        self.assertIn("prompt", public["tools"][0]["nodeMapping"])
        self.assertIn("image", public["tools"][0]["nodeMapping"])

    def test_invalid_modify_tool_is_not_exposed(self):
        public = build_public_config({
            "modifyTool": "missing",
            "tools": [{"id": "one", "name": "One", "nodeMapping": {}}],
        })
        self.assertNotIn("modifyTool", public)


if __name__ == "__main__":
    unittest.main()
