import os
import unittest
from unittest.mock import patch

from app.core import managed_runtime


class ManagedRuntimeTests(unittest.TestCase):
    def test_manifest_contains_pinned_comfyui_commit(self):
        manifest = managed_runtime.load_managed_runtime_manifest()
        comfy = manifest.get("comfyui", {})
        self.assertEqual(comfy.get("testedCommit"), "387f98aa2822f684b8597959a52a467d88cc4806")
        self.assertEqual(comfy.get("repository"), "https://github.com/Comfy-Org/ComfyUI.git")

    @patch("app.core.managed_runtime._read_state")
    @patch("app.core.managed_runtime._git_head")
    @patch("app.core.managed_runtime._comfyui_dir")
    def test_status_marks_tested_commit(self, comfy_dir, git_head, read_state):
        comfy_dir.return_value = "/tmp/comfy"
        git_head.return_value = "387f98aa2822f684b8597959a52a467d88cc4806"
        read_state.return_value = {"validation": "passed", "previousCommit": "oldsha"}

        status = managed_runtime.managed_runtime_status()
        self.assertTrue(status["managed"])
        self.assertTrue(status["matchesTested"])
        self.assertEqual(status["channel"], "tested")
        self.assertEqual(status["previousCommit"], "oldsha")
        self.assertEqual(status["validation"], "passed")

    @patch("app.core.managed_runtime._read_state")
    @patch("app.core.managed_runtime._git_head")
    @patch("app.core.managed_runtime._comfyui_dir")
    def test_status_marks_latest_as_untested(self, comfy_dir, git_head, read_state):
        comfy_dir.return_value = "/tmp/comfy"
        git_head.return_value = "newsha"
        read_state.return_value = {"channel": "latest", "validation": "pending"}

        status = managed_runtime.managed_runtime_status()
        self.assertFalse(status["matchesTested"])
        self.assertEqual(status["channel"], "latest")
        self.assertEqual(status["validation"], "pending")

    def test_value_unavailable_blocks_runtime_routing(self):
        backend = {
            "reachable": True,
            "errors": [],
            "warnings": [{"code": "value_unavailable", "message": "missing model"}],
        }
        self.assertFalse(managed_runtime._routing_compatible(backend))


if __name__ == "__main__":
    unittest.main()
