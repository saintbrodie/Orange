import unittest
from unittest.mock import patch

from app.api.llm_api import _resolve_tool_llm


class LLMResolutionTests(unittest.TestCase):
    @patch("app.api.llm_api.get_system_prompt", return_value="system")
    @patch("app.api.llm_api.load_config")
    @patch("app.api.llm_api.get_tool_settings")
    def test_tool_cannot_override_global_connection(self, get_tool, load_config, _system):
        get_tool.return_value = {
            "id": "z-image",
            "nodeMapping": {"prompt": {"nodeId": "1", "field": "text"}},
            "promptEnhance": {
                "enabled": True,
                "provider": "anthropic",
                "baseUrl": "https://stale.example",
                "apiKey": "stale-secret",
                "model": "tool-model",
            },
        }
        load_config.return_value = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "baseUrl": "http://localhost:11434/v1",
                "apiKey": "",
                "model": "global-model",
            }
        }

        resolved = _resolve_tool_llm("z-image")

        self.assertEqual(resolved["provider"], "openai")
        self.assertEqual(resolved["base_url"], "http://localhost:11434/v1")
        self.assertEqual(resolved["api_key"], "")
        self.assertEqual(resolved["model"], "tool-model")

    @patch("app.api.llm_api.get_system_prompt", return_value="system")
    @patch("app.api.llm_api.load_config")
    @patch("app.api.llm_api.get_tool_settings")
    def test_tool_without_model_uses_global_model(self, get_tool, load_config, _system):
        get_tool.return_value = {
            "id": "z-image",
            "nodeMapping": {"prompt": {"nodeId": "1", "field": "text"}},
            "promptEnhance": {"enabled": True},
        }
        load_config.return_value = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "baseUrl": "http://localhost:11434/v1",
                "model": "global-model",
            }
        }

        resolved = _resolve_tool_llm("z-image")
        self.assertEqual(resolved["model"], "global-model")


if __name__ == "__main__":
    unittest.main()
