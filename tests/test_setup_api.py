import os
import unittest
from unittest import mock

from app.api import setup


class SetupApiTests(unittest.TestCase):
    def test_setup_is_local_only_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ORANGE_ALLOW_REMOTE_SETUP", None)
            self.assertTrue(setup._setup_client_allowed("127.0.0.1"))
            self.assertTrue(setup._setup_client_allowed("::1"))
            self.assertTrue(setup._setup_client_allowed("localhost"))
            self.assertFalse(setup._setup_client_allowed("192.168.1.50"))
            self.assertFalse(setup._setup_client_allowed("example.test"))

    def test_remote_setup_can_be_explicitly_enabled(self):
        with mock.patch.dict(os.environ, {"ORANGE_ALLOW_REMOTE_SETUP": "1"}, clear=False):
            self.assertTrue(setup._setup_client_allowed("192.168.1.50"))

    def test_missing_model_warning_blocks_routing(self):
        backend = {
            "reachable": True,
            "errors": [],
            "warnings": [{"code": "value_unavailable", "value": "missing.safetensors"}],
        }
        self.assertFalse(setup._routing_compatible(backend))
        cached = setup._cacheable_preflight_results([backend])
        self.assertEqual(cached[0]["errors"][0]["code"], "routing_incompatible")

    def test_nonblocking_warning_keeps_backend_routable(self):
        backend = {
            "reachable": True,
            "errors": [],
            "warnings": [{"code": "node_metadata_incomplete"}],
        }
        self.assertTrue(setup._routing_compatible(backend))

    def test_new_setup_payload_can_select_no_curated_packs(self):
        self.assertEqual(
            setup._selected_pack_ids({"selectedPacks": []}, {"z-image-turbo", "krea-2-turbo"}),
            [],
        )

    def test_legacy_setup_payload_remains_backward_compatible(self):
        self.assertEqual(
            setup._selected_pack_ids(
                {"installStarter": True, "extraPacks": ["krea-2-turbo"]},
                {"z-image-turbo", "krea-2-turbo"},
            ),
            ["z-image-turbo", "krea-2-turbo"],
        )

    def test_setup_frontend_has_lost_response_recovery(self):
        source = os.path.join(os.path.dirname(__file__), "..", "static", "setup.js")
        with open(source, "r", encoding="utf-8") as handle:
            javascript = handle.read()
        self.assertIn("orange_setup_recovery_key", javascript)
        self.assertIn("recoverCompletedSetup", javascript)
        self.assertIn('window.location.replace("/admin")', javascript)

    def test_setup_uses_persistent_workflow_jobs(self):
        source = os.path.join(os.path.dirname(__file__), "..", "app", "api", "setup.py")
        with open(source, "r", encoding="utf-8") as handle:
            setup_source = handle.read()
        self.assertIn("create_job(pack_id, comfy_url, models_root)", setup_source)
        self.assertIn('schedule_install_job(job["id"])', setup_source)
        complete_body = setup_source.split('@router.post("/api/setup/complete")', 1)[1]
        self.assertNotIn("await asyncio.to_thread", complete_body)


if __name__ == "__main__":
    unittest.main()
