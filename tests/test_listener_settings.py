import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import admin
from app.core import access, listener, team
from app.main import app
from scripts import run_orange


class ListenerSettingsTests(unittest.TestCase):
    def test_legacy_open_lan_launcher_loads_http_option_once_at_startup(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(listener, "SETTINGS_PATH", Path(folder) / "listener.json"), \
                patch.dict(os.environ, {"ORANGE_RUNNING_PORT": "7070"}):
            os.environ.pop("ORANGE_RUNNING_LAN_HTTP", None)
            listener.save_settings(listener.ListenerSettings("open-lan", 7070, True))
            listener.load_open_lan_http_from_legacy_launcher()
            self.assertTrue(listener.lan_http_requested())
            self.assertTrue(listener.needs_launcher_relaunch(listener.ListenerSettings("team", 7070, True)))
            self.assertFalse(listener.needs_launcher_relaunch(listener.ListenerSettings("team", 7070)))
            listener.save_settings(listener.ListenerSettings("open-lan", 7070, False))
            self.assertTrue(listener.lan_http_requested())
            os.environ.pop("ORANGE_RUNNING_LAN_HTTP")
            listener.load_open_lan_http_from_legacy_launcher()
            self.assertFalse(listener.lan_http_requested())

    def test_save_and_restart_keep_active_settings_until_launcher_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            with patch.object(listener, "SETTINGS_PATH", path / "listener.json"), \
                    patch.object(listener, "RESTART_PATH", path / "restart"), \
                    patch.dict("os.environ", {"ORANGE_ACCESS_MODE": "local", "ORANGE_PORT": "7070",
                                              "ORANGE_RUNNING_ACCESS_MODE": "local", "ORANGE_RUNNING_PORT": "7070",
                                              "ORANGE_RUNNING_LAN_HTTP": "0"}), \
                    patch.object(admin, "load_config", return_value={"adminKey": "test-owner"}), \
                    patch.object(admin.team, "has_active_owner", return_value=False), \
                    patch.object(listener, "check_port") as check_port:
                client = TestClient(app)
                endpoint = "/api/admin/system/listener"
                headers = {"Authorization": "Bearer test-owner"}
                self.assertEqual(client.get(endpoint).status_code, 401)
                self.assertEqual(client.put(endpoint, headers=headers, json={"mode": "team", "port": 8080}).status_code, 409)
                self.assertEqual(client.put(endpoint, headers=headers, json={"mode": "local", "port": "8080"}).status_code, 422)
                check_port.side_effect = OSError("busy")
                self.assertEqual(client.put(endpoint, headers=headers, json={"mode": "open-lan", "port": 8080}).status_code, 409)
                self.assertFalse(listener.SETTINGS_PATH.exists())

                check_port.side_effect = None
                config = {"adminKey": "test-owner", "listenerSettings": {"mode": "open-lan", "port": 8080, "allow_lan_http": True}}
                with patch.object(admin, "save_config", side_effect=ValueError("invalid config")):
                    rejected = client.post("/api/admin/config", headers=headers, json=config)
                    self.assertEqual(rejected.status_code, 400)
                    self.assertFalse(listener.SETTINGS_PATH.exists())
                with patch.object(admin, "save_config") as save_config:
                    invalid = {**config, "listenerSettings": {"mode": "local", "port": 0}}
                    self.assertEqual(client.post("/api/admin/config", headers=headers, json=invalid).status_code, 422)
                    invalid = {**config, "listenerSettings": {"mode": "local", "port": 7070, "allow_lan_http": True}}
                    self.assertEqual(client.post("/api/admin/config", headers=headers, json=invalid).status_code, 422)
                    save_config.assert_not_called()
                    saved = client.post("/api/admin/config", headers=headers, json=config)
                    save_config.assert_called_once_with({"adminKey": "test-owner"})
                self.assertEqual(saved.status_code, 200, saved.text)
                self.assertEqual(saved.json()["listenerSettings"]["active"], {"mode": "local", "port": 7070, "allow_lan_http": False})
                self.assertEqual(saved.json()["listenerSettings"]["pending"], config["listenerSettings"])
                self.assertEqual(access.access_mode(), "local")
                self.assertFalse(listener.RESTART_PATH.exists())
                restart = client.post("/api/admin/system/restart", headers=headers)
                self.assertEqual(restart.status_code, 200, restart.text)
                self.assertTrue(listener.RESTART_PATH.exists())
                self.assertEqual(listener.configured_settings(), listener.ListenerSettings("open-lan", 8080, True))

    def test_admin_can_create_first_team_owner_as_part_of_saving_team_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            with patch.object(listener, "SETTINGS_PATH", path / "listener.json"), \
                    patch.object(access, "JOB_ACCESS_PATH", path / "team.db"), \
                    patch.dict(os.environ, {"ORANGE_RUNNING_ACCESS_MODE": "local", "ORANGE_RUNNING_PORT": "7070",
                                            "ORANGE_RUNNING_LAN_HTTP": "0"}), \
                    patch.object(admin, "load_config", return_value={"adminKey": "test-owner"}), \
                    patch.object(admin, "save_config") as save_config:
                client = TestClient(app)
                headers = {"Authorization": "Bearer test-owner"}
                endpoint = "/api/admin/system/team-setup"
                password = "owner-test-password"
                payload = {"adminKey": "test-owner", "listenerSettings": {"mode": "team", "port": 7070},
                           "teamOwner": {"handle": "First.Owner", "password": password}}
                self.assertFalse(client.get("/api/admin/system/listener", headers=headers).json()["team_owner_exists"])
                self.assertEqual(client.post(endpoint, json=payload).status_code, 401)
                self.assertEqual(client.post("/api/admin/config", json=payload, headers=headers).status_code, 400)
                invalid = {**payload, "teamOwner": {"handle": "First.Owner", "password": "short"}}
                self.assertEqual(client.post(endpoint, json=invalid, headers=headers).status_code, 400)
                self.assertFalse(team.has_active_owner())
                save_config.assert_not_called()

                response = client.post(endpoint, json=payload, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["listenerSettings"]["team_owner_exists"])
                self.assertEqual(response.json()["listenerSettings"]["pending"]["mode"], "team")
                self.assertNotIn(password, response.text)
                self.assertNotIn(password, listener.SETTINGS_PATH.read_text(encoding="utf-8"))
                save_config.assert_called_once_with({"adminKey": "test-owner"})
                user = team.current_user(team.login("first.owner", password))
                self.assertEqual(user["role"], "owner")

                self.assertEqual(client.post(endpoint, json=payload, headers=headers).status_code, 409)
                save_config.assert_called_once()

    def test_launcher_passes_saved_binding_and_probes_the_new_port(self):
        self.assertEqual(listener.ListenerSettings("team", 8080).host, "127.0.0.1")
        settings = listener.ListenerSettings("team", 8080, True)
        with patch.object(run_orange.subprocess, "Popen") as popen, \
                patch.object(run_orange.threading, "Thread"), \
                patch.object(run_orange, "wait_for_ready", return_value=True) as ready, \
                patch.object(run_orange, "RESTART_FILE") as restart_file, \
                patch.object(run_orange, "status"):
            restart_file.exists.return_value = False
            popen.return_value.poll.return_value = 0
            popen.return_value.returncode = 0
            self.assertEqual(run_orange.run_once(io.StringIO(), settings), (0, False, True))
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--host") + 1], "0.0.0.0")
            self.assertEqual(command[command.index("--port") + 1], "8080")
            self.assertEqual(popen.call_args.kwargs["env"]["ORANGE_RUNNING_ACCESS_MODE"], "team")
            self.assertEqual(popen.call_args.kwargs["env"]["ORANGE_RUNNING_LAN_HTTP"], "1")
            self.assertEqual(ready.call_args.args[2], "http://127.0.0.1:8080")
