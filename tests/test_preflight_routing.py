import time
import unittest
from unittest.mock import patch

from app.api.preflight import _routing_cache_results, _routing_compatible
from app.core.backends import BackendManager


class _FakeClient:
    def __init__(self):
        self.is_closed = False

    async def aclose(self):
        self.is_closed = True


class PreflightRoutingTests(unittest.IsolatedAsyncioTestCase):
    def test_unavailable_model_warning_blocks_routing_without_becoming_ui_error(self):
        backend = {
            "url": "http://server-a:8188",
            "reachable": True,
            "status": "warning",
            "errors": [],
            "warnings": [
                {
                    "code": "value_unavailable",
                    "field": "ckpt_name",
                    "value": "missing-model.safetensors",
                }
            ],
        }

        self.assertFalse(_routing_compatible(backend))
        self.assertEqual(backend["status"], "warning")
        self.assertEqual(backend["errors"], [])

        cached = _routing_cache_results([backend])[0]
        self.assertTrue(any(issue["code"] == "routing_incompatible" for issue in cached["errors"]))
        # The adapter must not mutate the result returned to the Admin UI.
        self.assertEqual(backend["errors"], [])

    def test_nonblocking_warning_remains_routable(self):
        backend = {
            "url": "http://server-a:8188",
            "reachable": True,
            "status": "warning",
            "errors": [],
            "warnings": [{"code": "unmanaged_image_input"}],
        }

        self.assertTrue(_routing_compatible(backend))
        self.assertEqual(_routing_cache_results([backend])[0]["errors"], [])

    async def test_missing_model_backend_is_skipped_for_that_workflow(self):
        servers = [
            {"url": "http://server-a:8188", "priority": 1},
            {"url": "http://server-b:8188", "priority": 2},
        ]
        manager = BackendManager()
        manager._client = _FakeClient()

        with patch("app.core.backends.get_comfy_servers", return_value=servers):
            manager._sync_servers()
            now = time.time()
            for state in manager._states.values():
                state.healthy = True
                state.last_checked = now
                state.latency_ms = 20

            preflight_results = [
                {
                    "url": "http://server-a:8188",
                    "reachable": True,
                    "errors": [],
                    "warnings": [{"code": "value_unavailable", "value": "missing-model.safetensors"}],
                },
                {
                    "url": "http://server-b:8188",
                    "reachable": True,
                    "errors": [],
                    "warnings": [],
                },
            ]
            manager.record_preflight("workflow-key", _routing_cache_results(preflight_results))
            selected = await manager.get_best_backend(compatibility_key="workflow-key")

        self.assertEqual(selected, "http://server-b:8188")


if __name__ == "__main__":
    unittest.main()
