from contextlib import ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sse_starlette.sse import AppStatus

from app.api import admin, generation_v2, media_providers, outputs, status, workflows
from app.core import access, database, media_jobs
from app.main import app


class AccessModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patches = ExitStack()
        self.addCleanup(patches.close)
        self.patch = patches.enter_context
        directory = Path(self.patch(tempfile.TemporaryDirectory()))
        self.patch(patch.dict("os.environ", {"ORANGE_ACCESS_MODE": "open-lan", "ORANGE_RUNNING_LAN_HTTP": "0"}))
        self.patch(patch.object(access, "JOB_ACCESS_PATH", directory / "access.db"))
        self.patch(patch.object(database, "DB_PATH", str(directory / "usage.db")))
        self.patch(patch.object(media_jobs, "OUTPUT_DIR", directory))
        self.patch(patch("app.main.setup_required", return_value=False))
        self.patch(patch.object(AppStatus, "should_exit_event", None))
        database.init_db()
        access.init_job_access()

    def browser(self, *, host="192.168.50.10", peer="192.168.50.12", listener_ip=None, peer_port=45000, scheme="http"):
        async def application(scope, receive, send):
            if listener_ip is not None:
                scope = {**scope, "server": (listener_ip, 7070)}
            await app(scope, receive, send)

        transport = httpx.ASGITransport(app=application, client=(peer, peer_port))
        return httpx.AsyncClient(transport=transport, base_url=f"{scheme}://{host}:7070")

    async def test_binding_policy_and_cross_site_writes(self):
        with patch.dict("os.environ", {"ORANGE_ACCESS_MODE": "local"}):
            async with self.browser() as lan, self.browser(host="127.0.0.1", peer="127.0.0.1") as local:
                self.assertEqual((await lan.get("/")).status_code, 403)
                self.assertEqual((await local.get("/")).status_code, 200)
                self.assertNotIn(access.GUEST_COOKIE, local.cookies)
        async with self.browser() as lan, self.browser(host="other.example") as wrong_host:
            self.assertEqual((await lan.get("/admin")).status_code, 403)
            self.assertEqual((await wrong_host.get("/")).status_code, 403)
            response = await lan.post("/api/generate", headers={"Origin": "http://other.example"})
            self.assertEqual(response.status_code, 403)

    async def test_open_lan_accepts_machine_names_and_explicit_aliases(self):
        access._machine_hostnames.cache_clear()
        self.addCleanup(access._machine_hostnames.cache_clear)
        self.patch(patch.object(access.socket, "gethostname", return_value="ORANGE-PC"))
        self.patch(patch.object(access, "_system_fqdn", return_value="Orange-PC.Office.Example"))
        self.patch(patch.dict("os.environ", {"ORANGE_LAN_HOSTS": "Render.Office.Example."}))

        for host in ("orange-pc", "ORANGE-PC.office.example", "orange-pc.office.example.", "render.office.example"):
            with self.subTest(host=host):
                async with self.browser(host=host) as guest:
                    self.assertEqual((await guest.get("/")).status_code, 200)
                    self.assertEqual((await guest.get("/admin")).status_code, 403)

        for host, peer in (("other.office.example", "192.168.50.12"), ("orange-pc.office.example", "198.51.100.25")):
            with self.subTest(host=host, peer=peer):
                async with self.browser(host=host, peer=peer) as guest:
                    self.assertEqual((await guest.get("/")).status_code, 403)

    async def test_open_lan_admin_accepts_the_host_using_its_dns_name(self):
        host = "orange-pc.office.example"
        local_ip = "192.168.50.10"
        self.patch(patch.object(access, "_machine_hostnames", return_value={host}))
        self.patch(patch.object(admin, "load_config", return_value={"adminKey": "test-owner"}))
        headers = {"Authorization": "Bearer test-owner"}
        async with self.browser(host=host, peer=local_ip, listener_ip=local_ip) as owner:
            self.assertEqual((await owner.get("/admin")).status_code, 200)
            self.assertEqual((await owner.get("/api/admin/config")).status_code, 401)
            self.assertEqual((await owner.get("/api/admin/config", headers=headers)).status_code, 200)

        for peer, port in (("192.168.50.12", 45000), (local_ip, 0)):
            async with self.browser(host=host, peer=peer, listener_ip=local_ip, peer_port=port) as remote:
                self.assertEqual((await remote.get("/admin")).status_code, 403)
                self.assertEqual((await remote.get("/api/admin/config", headers=headers)).status_code, 403)

        async with self.browser(host=host, listener_ip=local_ip, scheme="https") as remote:
            self.assertEqual((await remote.get("/api/admin/config", headers=headers)).status_code, 200)
            with patch.object(admin, "load_config", return_value={"adminKey": "orangeadmin"}):
                self.assertEqual((await remote.get("/api/admin/config", headers={"Authorization": "Bearer orangeadmin"})).status_code, 403)

        with patch.dict("os.environ", {"ORANGE_RUNNING_LAN_HTTP": "1"}):
            async with self.browser(host=host, listener_ip=local_ip) as remote:
                self.assertEqual((await remote.get("/admin")).status_code, 200)
                self.assertEqual((await remote.get("/api/admin/config")).status_code, 401)
                self.assertEqual((await remote.get("/api/admin/config", headers=headers)).status_code, 200)
                with patch.object(admin, "load_config", return_value={"adminKey": "orangeadmin"}):
                    self.assertEqual((await remote.get("/api/admin/config", headers=headers)).status_code, 401)
                    self.assertEqual((await remote.get("/api/admin/config", headers={"Authorization": "Bearer orangeadmin"})).status_code, 200)
            for peer, port in (("198.51.100.25", 45000), ("192.168.50.12", 0)):
                async with self.browser(host=host, peer=peer, listener_ip=local_ip, peer_port=port) as remote:
                    self.assertEqual((await remote.get("/admin")).status_code, 403)

    async def test_comfy_jobs_are_private_to_the_browser_across_aliases(self):
        tool = {"id": "comfy", "workflowFile": "test.json", "nodeMapping": {}}
        backend = "http://comfy.example"
        history = {"backend-prompt": {"outputs": {"1": {"images": [{"filename": "result.png"}]}}}}
        comfy = AsyncMock()
        comfy.get.side_effect = lambda url, **_: httpx.Response(
            200, json=history,
        ) if "/history/" in url else httpx.Response(200, content=b"image")
        for name, value in {
            "get_tool_settings": tool,
            "get_base_workflow": {},
            "get_best_backend": backend,
            "get_backend_client": comfy,
            "get_comfy_servers": [],
            "backend_inventory": {},
            "resolve_models": {"workflow": {}, "models": [], "errors": []},
            "submit_prompt": {"prompt_id": "backend-prompt"},
        }.items():
            self.patch(patch.object(generation_v2, name, return_value=value))
        self.patch(patch.object(outputs, "get_backend_client", return_value=comfy))
        self.patch(patch.object(status, "get_backend_client", return_value=comfy))
        stream = self.patch(patch.object(status, "status_generator", wraps=status.status_generator))

        async with self.browser() as first, self.browser() as second:
            for guest in (first, second):
                page = await guest.get("/")
                self.assertEqual(page.status_code, 200)
                self.assertIn("HttpOnly", page.headers["set-cookie"])
            self.assertNotEqual(first.cookies[access.GUEST_COOKIE], second.cookies[access.GUEST_COOKIE])

            result = await first.post("/api/generate", data={"tool_id": "comfy"})
            self.assertEqual(result.status_code, 200, result.text)
            job_id = result.json()["prompt_id"]
            self.assertNotEqual(job_id, "backend-prompt")

            query = {"prompt_id": job_id, "client_id": "ignored", "tool_id": "ignored"}
            self.assertEqual((await second.get("/api/status", params=query)).status_code, 404)
            self.assertIn('"completed"', (await first.get("/api/status", params=query)).text)
            args, kwargs = stream.call_args
            self.assertEqual(args[1], "backend-prompt")
            self.assertNotEqual(args[2], "ignored")
            self.assertEqual(args[3], "comfy")
            self.assertEqual(kwargs["target_url"], backend)

            for route in ("outputs", "output", "image", "media"):
                http_path = f"/api/{route}"
                self.assertEqual((await second.get(http_path, params={"prompt_id": job_id})).status_code, 404)
                owned = await first.get(http_path, params={"prompt_id": job_id})
                self.assertEqual(owned.status_code, 200, owned.text)
                self.assertEqual(owned.headers["cache-control"], "no-store")
                self.assertEqual((await first.get(http_path, params={"prompt_id": "backend-prompt"})).status_code, 404)

    async def test_cloud_tools_opt_in_and_only_the_owner_can_retry(self):
        tool = {"id": "cloud", "name": "Cloud", "provider": "openai", "api": {
            "ratios": ["1:1"], "resolutions": ["1k"], "defaultResolution": "1k",
        }}
        self.patch(patch.object(generation_v2, "get_tool_settings", return_value=tool))
        self.patch(patch.object(workflows, "load_config", return_value={"tools": [tool]}))
        self.patch(patch.object(media_providers, "validate_api_tool", return_value=SimpleNamespace(
            id="image", output="image", prompt_limit=1000,
        )))
        self.patch(patch.object(media_providers.config, "ready", return_value=True))
        schedule = self.patch(patch.object(media_jobs.job_manager, "_schedule"))
        retry = self.patch(patch.object(media_jobs.job_manager, "retry_delivery"))
        self.patch(patch.object(admin, "get_comfy_servers", return_value=[]))
        self.patch(patch.object(admin, "load_config", return_value={"adminKey": "test-owner"}))
        self.patch(patch.object(access, "load_config", return_value={"adminKey": "test-owner"}))
        request = {"tool_id": "cloud", "prompt": "private text"}

        async with self.browser() as first, self.browser() as second:
            self.assertEqual((await first.get("/api/workflows")).json()["tools"], [])
            self.assertEqual((await first.post("/api/generate", data=request)).status_code, 403)
            schedule.assert_not_called()

            with patch.dict("os.environ", {"ORANGE_LAN_TOOLS": "cloud"}):
                response = await first.post("/api/generate", data=request)
            self.assertEqual(response.status_code, 200, response.text)
            job_id = response.json()["prompt_id"]
            schedule.assert_called_once()
            retry_path = f"/api/jobs/{job_id}/retry-download"
            media_jobs._update(job_id, "delivery_failed")
            self.assertEqual((await second.post(retry_path)).status_code, 404)
            retry.assert_not_called()
            self.assertEqual((await first.post(retry_path)).status_code, 202)
            retry.assert_called_once()

            filename = f"{job_id}-0.png"
            media_jobs.output_path(filename).write_bytes(b"image")
            media_jobs._update(job_id, "completed", outputs=[{"filename": filename, "media_type": "image/png"}])
            params = {"prompt_id": job_id, "client_id": "ignored"}
            self.assertEqual((await second.get("/api/status", params=params)).status_code, 404)
            self.assertIn('"completed"', (await first.get("/api/status", params=params)).text)
            self.assertEqual((await first.get("/api/media", params=params)).content, b"image")
            self.assertEqual((await second.get("/api/media", params=params)).status_code, 404)

        self.patch(patch.object(access, "_machine_hostnames", return_value={"orange-pc.office.example"}))
        with patch.dict("os.environ", {"ORANGE_RUNNING_LAN_HTTP": "1"}):
            async with self.browser(host="orange-pc.office.example", listener_ip="192.168.50.10") as owner:
                self.assertEqual((await owner.get("/api/output", params=params)).status_code, 404)
                headers = {"Authorization": "Bearer test-owner"}
                self.assertEqual((await owner.get("/api/admin/media", headers=headers)).status_code, 200)
                self.assertEqual((await owner.get("/api/output", params=params)).content, b"image")
                await owner.delete("/api/admin/media/session")
                self.assertEqual((await owner.get("/api/output", params=params)).status_code, 404)

    def test_analytics_counts_latest_job_outcome_without_private_fields(self):
        database.log_usage("192.168.50.12", "comfy", "private prompt", prompt_id="same-job")
        database.log_usage("192.168.50.12", "comfy", "private prompt", prompt_id="same-job", status="completed")
        database.log_usage("192.168.50.12", "comfy", "private prompt", status="submission_failed")
        report = admin.get_admin_usage(period="today", export=True, _=True)
        self.assertEqual(report["total"], 2)
        self.assertEqual({row["status"] for row in report["status_summary"]}, {"completed", "submission_failed"})
        self.assertTrue(all(set(row) == {"id", "timestamp", "tool_id", "provider", "model", "status"} for row in report["logs"]))
