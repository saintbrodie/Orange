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


if __name__ == "__main__":
    unittest.main()
