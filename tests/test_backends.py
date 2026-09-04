import time
import unittest
from unittest.mock import patch

from app.core.backends import BackendManager, workflow_compatibility_key


class _FakeClient:
    def __init__(self):
        self.is_closed = False

    async def aclose(self):
        self.is_closed = True


class BackendManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.servers = [
            {"url": "http://server-a:8188", "priority": 1},
            {"url": "http://server-b:8188", "priority": 2},
        ]
        self.manager = BackendManager()
        self.manager._client = _FakeClient()
        self.server_patch = patch("app.core.backends.get_comfy_servers", return_value=self.servers)
        self.server_patch.start()
        self.manager._sync_servers()

        now = time.time()
        for state in self.manager._states.values():
            state.healthy = True
            state.last_checked = now
            state.latency_ms = 20

    def tearDown(self):
        self.server_patch.stop()

    async def test_lower_effective_queue_wins_before_priority(self):
        self.manager._states["http://server-a:8188"].queue_pending = 3
        self.manager._states["http://server-b:8188"].queue_pending = 1

        selected = await self.manager.get_best_backend()

        self.assertEqual(selected, "http://server-b:8188")

    async def test_priority_breaks_queue_ties(self):
        selected = await self.manager.get_best_backend()

        self.assertEqual(selected, "http://server-a:8188")

    async def test_active_requests_are_counted_in_routing_score(self):
        self.manager._states["http://server-a:8188"].active_requests = 2

        selected = await self.manager.get_best_backend()

        self.assertEqual(selected, "http://server-b:8188")

    async def test_preflight_incompatible_backend_is_skipped(self):
        self.manager.record_preflight(
            "workflow-key",
            [
                {"url": "http://server-a:8188", "reachable": True, "errors": [{"code": "missing"}]},
                {"url": "http://server-b:8188", "reachable": True, "errors": []},
            ],
        )

        selected = await self.manager.get_best_backend(compatibility_key="workflow-key")

        self.assertEqual(selected, "http://server-b:8188")

    async def test_circuit_open_backend_is_skipped(self):
        self.manager.failure_threshold = 1
        self.manager.record_failure("http://server-a:8188", "boom")

        selected = await self.manager.get_best_backend()

        self.assertEqual(selected, "http://server-b:8188")

    def test_workflow_fingerprint_changes_when_mapping_changes(self):
        workflow = {"1": {"class_type": "Example", "inputs": {"text": "hello"}}}
        first = workflow_compatibility_key(
            "example.json",
            workflow,
            {"prompt": {"nodeId": "1", "field": "text"}},
        )
        second = workflow_compatibility_key(
            "example.json",
            workflow,
            {"prompt": {"nodeId": "1", "field": "other"}},
        )

        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
