import json
import os
import tempfile
import unittest
from unittest import mock

from app.core import onboarding


class OnboardingTests(unittest.TestCase):
    def test_fresh_install_requires_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "setup-state.json")
            config_path = os.path.join(tmp, "workflows-config.json")
            with mock.patch.object(onboarding, "SETUP_STATE_PATH", state_path), mock.patch.object(
                onboarding, "USER_CONFIG_PATH", config_path
            ):
                onboarding.initialize_setup_state(was_fresh_install=True)
                with open(state_path, "r", encoding="utf-8") as handle:
                    state = json.load(handle)

                self.assertFalse(state["complete"])
                self.assertTrue(onboarding.setup_required())

    def test_existing_install_is_migrated_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "setup-state.json")
            config_path = os.path.join(tmp, "workflows-config.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("{}")

            with mock.patch.object(onboarding, "SETUP_STATE_PATH", state_path), mock.patch.object(
                onboarding, "USER_CONFIG_PATH", config_path
            ):
                onboarding.initialize_setup_state(was_fresh_install=False)
                with open(state_path, "r", encoding="utf-8") as handle:
                    state = json.load(handle)

                self.assertTrue(state["complete"])
                self.assertTrue(state["migratedExistingInstall"])
                self.assertFalse(onboarding.setup_required())

    def test_mark_setup_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "setup-state.json")
            config_path = os.path.join(tmp, "workflows-config.json")
            with mock.patch.object(onboarding, "SETUP_STATE_PATH", state_path), mock.patch.object(
                onboarding, "USER_CONFIG_PATH", config_path
            ):
                onboarding.initialize_setup_state(was_fresh_install=True)
                onboarding.mark_setup_complete()

                self.assertFalse(onboarding.setup_required())


if __name__ == "__main__":
    unittest.main()
