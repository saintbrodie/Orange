import asyncio
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
import secrets
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from PIL import Image
from sse_starlette.sse import AppStatus

from app.api import generation_v2, media_providers, outputs, status, workflows
from app.api import team as team_api
from app.core import access, budgets, database, media_jobs, team
from app.core.media_aggregators import raster_result
from app.core.media_providers import Media, ProviderResult
from app.main import app

PASSWORD = "a-long-test-password"
CLOUD_TOOL = {"id": "cloud", "name": "Cloud", "provider": "openai", "model": "image", "api": {
    "ratios": ["1:1"], "resolutions": ["1k"], "defaultResolution": "1k",
}}
COMFY_TOOL = {"id": "comfy", "name": "Comfy", "workflowFile": "test.json", "nodeMapping": {}}


class TeamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.patch = stack.enter_context
        directory = Path(self.patch(tempfile.TemporaryDirectory()))
        self.patch(patch.dict("os.environ", {"ORANGE_ACCESS_MODE": "team", "ORANGE_TEAM_ORIGIN": "https://team.example",
                                              "ORANGE_RUNNING_LAN_HTTP": "0"}))
        self.patch(patch.object(access, "JOB_ACCESS_PATH", directory / "access.db"))
        self.patch(patch.object(database, "DB_PATH", str(directory / "usage.db")))
        self.patch(patch.object(media_jobs, "OUTPUT_DIR", directory))
        self.patch(patch("app.main.setup_required", return_value=False))
        self.patch(patch.object(AppStatus, "should_exit_event", None))
        self.patch(patch.object(team_api, "load_config", return_value={"tools": [CLOUD_TOOL, COMFY_TOOL]}))
        tools = {tool["id"]: tool for tool in (CLOUD_TOOL, COMFY_TOOL)}
        for router in (team_api, generation_v2):
            self.patch(patch.object(router, "get_tool_settings", side_effect=tools.get))
        self.patch(patch.object(workflows, "load_config", return_value={"tools": [COMFY_TOOL]}))
        team_api._AUTH_LIMIT.reset()
        team.init_team()
        budgets.init_budgets()
        database.init_db()
        team.bootstrap_owner("owner", PASSWORD)
        self.invite_expiry = int(time.time()) + 3600
        with access.job_db() as connection:
            self.owner_id = team.list_users(connection)[0]["id"]

    def client(self, address="https://team.example", peer="192.168.40.12"):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(peer, 45000)), base_url=address)

    async def login(self, client, handle="owner"):
        response = await client.post("/api/team/login", json={"handle": handle, "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("Secure", response.headers["set-cookie"])
        self.assertIn("__Host-orange_team", response.headers["set-cookie"])

    async def add_user(self, owner, client, handle, role="member"):
        invitation = await owner.post("/api/team/invitations", json={"role": role, "expires": self.invite_expiry})
        self.assertEqual(invitation.status_code, 201, invitation.text)
        token = invitation.json()["token"]
        response = await client.post("/api/team/accept-invitation", json={"token": token, "password": PASSWORD, "handle": handle})
        self.assertEqual(response.status_code, 200, response.text)
        return (await client.get("/api/team/session")).json()["user"]["id"]

    async def test_invites_roles_logout_and_disablement(self):
        async with self.client() as owner, self.client() as operator, self.client() as member, \
                self.client("http://team.example") as insecure:
            self.assertEqual((await insecure.get("/team")).status_code, 403)
            self.assertEqual((await member.get("/")).headers["location"], "/team")
            self.assertEqual((await member.get("/api/workflows")).status_code, 401)
            self.assertEqual((await member.get("/team")).status_code, 200)
            self.assertEqual((await member.get("/team", params={"embedded": 1})).headers["location"], "/team")
            self.assertEqual((await member.get("/api/admin/config", headers={"Authorization": "Bearer orangeadmin"})).status_code, 401)
            await self.login(owner)
            await self.add_user(owner, operator, "operator", "operator")
            member_id = await self.add_user(owner, member, "member")
            self.assertIn('data-orange-mode="team"', (await owner.get("/admin")).text)
            self.assertIn('id="tab-team"', (await owner.get("/admin")).text)
            self.assertIn('data-team-embedded', (await owner.get("/team", params={"embedded": 1})).text)
            self.assertIn('href="/team"', (await member.get("/")).text)
            self.assertEqual((await operator.get("/admin")).headers["location"], "/team")
            self.assertEqual((await operator.get("/team", params={"embedded": 1})).status_code, 403)
            self.assertEqual((await owner.get("/api/admin/media")).status_code, 403)
            self.assertEqual((await operator.get("/api/admin/config")).status_code, 403)
            self.assertEqual((await member.get("/api/admin/usage")).status_code, 403)
            database.log_usage("127.0.0.1", "comfy", "private", prompt_id="legacy")
            self.assertEqual((await operator.get("/api/admin/usage")).json()["logs"], [])
            self.assertEqual((await operator.get("/api/admin/usage?export=true")).status_code, 403)
            self.assertEqual((await operator.post("/api/team/invitations", json={"role": "operator", "expires": self.invite_expiry})).status_code, 403)
            self.assertEqual((await operator.put("/api/team/tools/comfy", json={"enabled": False})).status_code, 403)
            self.assertEqual((await owner.put("/api/team/tools/comfy", json={"enabled": False})).status_code, 200)
            self.assertEqual((await member.get("/api/workflows")).json()["tools"], [])
            self.assertEqual((await member.post("/api/generate", data={"tool_id": "comfy"})).status_code, 403)
            self.assertNotIn("members", (await member.get("/api/team/spend")).json())

            owner_path = f"/api/team/users/{self.owner_id}"
            self.assertEqual((await owner.patch(owner_path, json={"enabled": False})).status_code, 409)
            self.assertEqual((await owner.patch(owner_path, json={"role": "member"})).status_code, 409)
            self.assertEqual((await owner.patch(owner_path, json={"reset": True})).status_code, 409)
            self.assertEqual((await owner.delete(owner_path)).status_code, 409)
            self.assertEqual((await owner.patch(f"/api/team/users/{member_id}", json={"enabled": False})).status_code, 200)
            self.assertEqual((await member.get("/api/team/generations")).status_code, 401)
            self.assertEqual((await member.post("/api/team/login", json={"handle": "member", "password": PASSWORD})).status_code, 401)

            self.assertEqual((await operator.post("/api/team/logout", headers={"Origin": "https://elsewhere.example"})).status_code, 403)
            token = operator.cookies["__Host-orange_team"]
            self.assertEqual((await operator.post("/api/team/logout")).status_code, 200)
            self.assertIsNone(team.current_user(token))
            self.assertEqual((await operator.get("/api/team/session")).json(), {"user": None})

    async def test_operator_can_invite_and_reset_members(self):
        async with self.client() as owner, self.client() as operator, self.client() as member:
            await self.login(owner)
            operator_id = await self.add_user(owner, operator, "operator", "operator")
            member_id = await self.add_user(operator, member, "new-member")
            account = f"/api/team/users/{member_id}"
            for change in ({"role": "operator", "reset": True}, {"enabled": False}, {"role": "owner"}):
                self.assertEqual((await operator.patch(account, json=change)).status_code, 403)
            for protected_id in (self.owner_id, operator_id):
                self.assertEqual((await operator.patch(f"/api/team/users/{protected_id}", json={"reset": True})).status_code, 403)
            self.assertEqual((await member.post("/api/team/invitations", json={"expires": self.invite_expiry})).status_code, 403)
            self.assertEqual((await member.patch(account, json={"reset": True})).status_code, 403)

            reset = await operator.patch(account, json={"reset": True})
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertIsNone((await member.get("/api/team/session")).json()["user"])
            old = await member.post("/api/team/login", json={"handle": "new-member", "password": PASSWORD})
            self.assertEqual(old.status_code, 401)
            invite = reset.json()["invitation"]["token"]
            new_password = PASSWORD + "-new"
            accepted = await member.post("/api/team/accept-invitation", json={"token": invite, "password": new_password})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            replay = await member.post("/api/team/accept-invitation", json={"token": invite, "password": new_password})
            self.assertEqual(replay.status_code, 400)
            self.assertEqual((await member.get("/api/team/session")).json()["user"]["id"], member_id)

            promoted = await owner.patch(account, json={"role": "operator"})
            self.assertTrue(promoted.json()["invitation"]["token"])
            old_login = await member.post("/api/team/login", json={"handle": "new-member", "password": new_password})
            self.assertEqual(old_login.status_code, 401)
            privileged_reset = await owner.patch(f"/api/team/users/{operator_id}", json={"reset": True})
            self.assertEqual(privileged_reset.status_code, 200, privileged_reset.text)
            self.assertTrue(privileged_reset.json()["invitation"]["token"])

    async def test_group_and_account_tool_policies_apply_to_catalog_and_generation(self):
        cloud = {**CLOUD_TOOL, "model": "gpt-image-1.5", "outputType": "image",
                 "api": {"ratios": ["1:1"], "resolutions": ["standard"], "defaultResolution": "standard"}}
        config = {"tools": [cloud, COMFY_TOOL]}
        self.patch(patch.object(workflows, "load_config", return_value=config))
        self.patch(patch.object(team_api, "load_config", return_value=config))
        self.patch(patch.object(status, "get_tool_settings", return_value=cloud))
        async with self.client() as owner, self.client() as operator, self.client() as member:
            await self.login(owner)
            await self.add_user(owner, operator, "operator", "operator")
            member_id = await self.add_user(owner, member, "designer")
            user_tools = f"/api/team/users/{member_id}/tools"
            groups = "/api/team/groups"

            async def visible():
                response = await member.get("/api/workflows")
                return {tool["id"] for tool in response.json()["tools"]}

            self.assertEqual(await visible(), {"comfy", "cloud"})
            graphics = {"name": "Graphics", "restricted": True, "tool_ids": ["comfy"]}
            self.assertEqual((await operator.post(groups, json=graphics)).status_code, 403)
            graphics_response = await owner.post(groups, json=graphics)
            self.assertEqual(graphics_response.status_code, 201, graphics_response.text)
            graphics_url = f"{groups}/{graphics_response.json()['id']}"
            assigned = await owner.put("/api/team/memberships", json={
                "action": "add", "team_id": graphics_response.json()["id"], "user_ids": [member_id],
            })
            self.assertEqual(assigned.json(), {"updated": 1})
            self.assertEqual(await visible(), {"comfy"})
            self.assertEqual((await member.post("/api/generate", data={"tool_id": "cloud"})).status_code, 403)
            self.assertEqual((await member.get("/api/health", params={"tool_id": "cloud"})).status_code, 403)
            self.assertEqual((await member.post("/api/enhance-prompt", data={"tool_id": "unknown", "prompt": "hello"})).status_code, 403)
            with self.assertRaises(HTTPException) as denied:
                budgets.reserve_cloud_job("api-denied", member_id, cloud, "image")
            self.assertIn("unavailable for your account", denied.exception.detail)

            social = {**graphics, "name": "Social Media", "tool_ids": ["cloud"]}
            social_response = await owner.post(groups, json=social)
            self.assertEqual(social_response.status_code, 201, social_response.text)
            social_url = f"{groups}/{social_response.json()['id']}"
            assigned = await owner.put("/api/team/memberships", json={
                "action": "add", "team_id": social_response.json()["id"], "user_ids": [member_id],
            })
            self.assertEqual(assigned.json(), {"updated": 1})
            self.assertEqual(await visible(), {"comfy", "cloud"})
            settings = {"overrides": {"comfy": "deny", "cloud": "allow"}}
            self.assertEqual((await operator.put(user_tools, json=settings)).status_code, 403)
            self.assertEqual((await owner.put(user_tools, json=settings)).status_code, 200)
            self.assertEqual((await owner.delete(social_url)).status_code, 204)
            self.assertEqual(await visible(), {"cloud"})
            self.assertEqual((await member.post("/api/generate", data={"tool_id": "comfy"})).status_code, 403)
            self.assertEqual((await owner.put("/api/team/tools/cloud", json={"enabled": False})).status_code, 200)
            self.assertEqual(await visible(), set())

            details = (await owner.get(f"/api/team/users/{member_id}")).json()
            self.assertEqual([group["name"] for group in details["teams"]], ["Graphics"])
            self.assertEqual({tool["id"]: tool["override"] for tool in details["tools"]}, settings["overrides"])
            self.assertFalse(any(tool["available"] for tool in details["tools"]))
            self.assertEqual((await owner.put(graphics_url, json={**graphics, "restricted": False})).status_code, 200)
            self.assertEqual((await owner.put(user_tools, json={"overrides": {}})).status_code, 200)
            self.assertEqual(await visible(), {"comfy"})

    async def test_directory_pages_and_moves_memberships_across_200_accounts(self):
        async with self.client() as owner, self.client() as operator:
            await self.login(owner)
            await self.add_user(owner, operator, "operator", "operator")
            seeded = [(f"{index + 1000:032x}", f"staff-{index:03}") for index in range(200)]
            with access.job_db() as connection:
                connection.executemany("""INSERT INTO team_users (id, handle, role, password_hash, enabled, created_at)
                    VALUES (?, ?, 'member', 'fixture', ?, ?)""", (
                    (user_id, handle, index != 199, 1700000000 + index if index else None)
                    for index, (user_id, handle) in enumerate(seeded)
                ))

            async def create_group(name):
                result = await owner.post("/api/team/groups", json={"name": name, "restricted": False, "tool_ids": []})
                self.assertEqual(result.status_code, 201, result.text)
                return result.json()["id"]

            graphics, social, print_team = [await create_group(name) for name in ("Graphics", "Social", "Print")]
            accounts = "/api/team/accounts"
            matches = {"query": "STAFF-", "role": "member"}
            result = (await owner.get(accounts, params={**matches, "page": 8})).json()
            self.assertEqual((result["total"], result["page"], len(result["accounts"])), (200, 8, 25))
            self.assertEqual(result["accounts"][0]["handle"], "staff-175")
            dated = (await owner.get(accounts, params={**matches, "sort": "date", "descending": True, "page": 8})).json()
            self.assertEqual(dated["accounts"][-1]["handle"], "staff-000")
            self.assertIsNone(dated["accounts"][-1]["created_at"])
            disabled = (await owner.get(accounts, params={**matches, "status": "disabled"})).json()
            self.assertEqual([user["handle"] for user in disabled["accounts"]], ["staff-199"])
            operator_first = (await operator.get(accounts, params={**matches, "page_size": 50})).json()
            self.assertEqual(len(operator_first["accounts"]), 50)
            self.assertEqual((await operator.get(accounts, params={**matches, "selection": True})).status_code, 403)
            selection = (await owner.get(accounts, params={**matches, "selection": True})).json()["ids"]
            self.assertEqual(set(selection), {user_id for user_id, _ in seeded})

            endpoint = "/api/team/memberships"
            payload = {"action": "add", "team_id": graphics, "user_ids": selection}
            self.assertEqual((await operator.put(endpoint, json=payload)).status_code, 403)
            self.assertEqual((await owner.put(endpoint, json=payload)).json(), {"updated": 200})
            member = seeded[25][0]
            self.assertEqual((await owner.put(endpoint, json={"action": "add", "team_id": print_team, "user_ids": [member]})).json(), {"updated": 1})
            moved = await owner.put(endpoint, json={
                "action": "move", "source_team_id": graphics, "team_id": social, "user_ids": [user_id for user_id, _ in seeded[25:35]],
            })
            self.assertEqual(moved.json(), {"updated": 10})
            page = (await owner.get(accounts, params={"team": social, "sort": "team"})).json()
            self.assertEqual(page["total"], 10)
            self.assertEqual([group["name"] for group in page["accounts"][0]["teams"]], ["Print", "Social"])
            self.assertEqual((await owner.get(accounts, params={**matches, "team": "unassigned"})).json()["total"], 0)
            edit = await owner.put(f"/api/team/groups/{graphics}", json={"name": "Graphics", "restricted": True, "tool_ids": ["comfy"]})
            self.assertEqual(edit.status_code, 200, edit.text)
            groups = (await owner.get("/api/team/groups")).json()["groups"]
            self.assertEqual({group["name"]: group["member_count"] for group in groups}, {"Graphics": 190, "Print": 1, "Social": 10})
            self.assertTrue(all("member_ids" not in group for group in groups))
            await owner.put(endpoint, json={"action": "remove", "team_id": social, "user_ids": [member]})
            details = (await owner.get(f"/api/team/users/{member}")).json()
            self.assertEqual([group["name"] for group in details["teams"]], ["Print"])

    async def test_shared_invite_lets_multiple_members_join_until_expiry(self):
        async with self.client() as owner, self.client() as operator, self.client() as first, self.client() as second:
            await self.login(owner)
            await self.add_user(owner, operator, "operator", "operator")
            invite_path = "/api/team/invitations"
            accept_path = "/api/team/accept-invitation"
            expired = await owner.post(invite_path, json={"expires": int(time.time()) - 1})
            self.assertEqual(expired.status_code, 400)
            named = await owner.post(invite_path, json={"expires": self.invite_expiry, "handle": "reserved"})
            self.assertEqual(named.status_code, 422)
            issued = await operator.post(invite_path, json={"expires": self.invite_expiry})
            self.assertEqual(issued.status_code, 201, issued.text)
            self.assertEqual(issued.json()["expires"], self.invite_expiry)
            token = issued.json()["token"]
            self.assertTrue(token.startswith(team.SHARED_INVITE_PREFIX))
            payload = {"token": token, "password": PASSWORD}
            self.assertEqual((await first.post(accept_path, json=payload)).status_code, 400)
            self.assertEqual((await first.post(accept_path, json={**payload, "handle": "OWNER"})).status_code, 409)
            responses = await asyncio.gather(
                first.post(accept_path, json={**payload, "handle": "First.User"}),
                second.post(accept_path, json={**payload, "handle": "Second.User"}),
            )
            self.assertEqual([response.status_code for response in responses], [200, 200])
            for client, name in ((first, "first.user"), (second, "second.user")):
                account = (await client.get("/api/team/session")).json()["user"]
                self.assertEqual((account["handle"], account["role"]), (name, "member"))
            with patch.object(team, "time", wraps=time) as clock:
                clock.time.return_value = self.invite_expiry
                expired = await second.post(accept_path, json={**payload, "handle": "too-late"})
                self.assertEqual(expired.status_code, 400)

    async def test_direct_accounts_can_sign_in_and_staff_can_remove_them(self):
        async with self.client() as owner, self.client() as operator, self.client() as member:
            await self.login(owner)
            create = "/api/team/users"
            credentials = {"handle": "operator", "password": PASSWORD, "role": "operator"}
            operator_account = await owner.post(create, json=credentials)
            self.assertEqual(operator_account.status_code, 201, operator_account.text)
            operator_path = f"{create}/{operator_account.json()['id']}"
            await self.login(operator, "operator")
            elevated = await operator.post(create, json={**credentials, "handle": "another-operator"})
            self.assertEqual(elevated.status_code, 403)
            self.assertEqual((await operator.delete(operator_path)).status_code, 403)
            self.assertEqual((await operator.delete(f"{create}/{self.owner_id}")).status_code, 403)

            credentials = {"handle": "New.Member", "password": PASSWORD}
            short_password = await operator.post(create, json={**credentials, "password": "short"})
            self.assertEqual(short_password.status_code, 400)
            created = await operator.post(create, json=credentials)
            self.assertEqual(created.status_code, 201, created.text)
            member_id = created.json()["id"]
            member_path = f"{create}/{member_id}"
            self.assertEqual(created.json(), {"id": member_id, "handle": "new.member", "role": "member"})
            self.assertEqual((await operator.post(create, json=credentials)).status_code, 409)
            await self.login(member, "new.member")
            self.assertEqual((await member.post(create, json=credentials)).status_code, 403)
            self.assertEqual((await member.delete(member_path)).status_code, 403)

            budgets.set_workspace_limit(self.owner_id, 500_000)
            budgets.set_tool_price(self.owner_id, CLOUD_TOOL, 300_000)
            job_id = f"api-{'1' * 32}"
            budgets.reserve_cloud_job(job_id, member_id, CLOUD_TOOL, "image")
            budgets.mark_dispatched(job_id)
            self.assertEqual((await operator.delete(member_path)).status_code, 204)
            self.assertEqual((await member.get("/api/team/session")).json(), {"user": None})
            old_login = await member.post("/api/team/login", json=credentials)
            self.assertEqual(old_login.status_code, 401)
            self.assertEqual((await owner.patch(member_path, json={"enabled": True})).status_code, 404)
            self.assertEqual((await owner.delete(member_path)).status_code, 404)

            budgets.record_job_status(job_id, "completed", terminal=True, reported_micros=150_000)
            report = (await owner.get("/api/team/spend")).json()
            self.assertEqual(report["workspace"]["reported_micros"], 150_000)
            self.assertNotIn(member_id, {account["id"] for account in report["members"]})
            replacement = await operator.post(create, json=credentials)
            self.assertEqual(replacement.status_code, 201, replacement.text)
            self.assertNotEqual(replacement.json()["id"], member_id)
            await self.login(member, "new.member")
            self.assertEqual((await member.get("/api/team/generations")).json(), {"jobs": []})

            replacement_path = f"{create}/{replacement.json()['id']}"
            reset = await owner.patch(replacement_path, json={"reset": True})
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertEqual((await owner.delete(replacement_path)).status_code, 204)
            accepted = await member.post("/api/team/accept-invitation", json={
                "token": reset.json()["invitation"]["token"], "password": PASSWORD,
            })
            self.assertEqual(accepted.status_code, 400)
            self.assertEqual((await owner.delete(operator_path)).status_code, 204)
            self.assertEqual((await operator.get("/api/team/session")).json(), {"user": None})

    async def test_legacy_general_invite_still_works_once(self):
        token = team.MEMBER_INVITE_PREFIX + secrets.token_urlsafe(32)
        with access.job_db() as connection:
            connection.execute("INSERT INTO team_member_invites (digest, expires) VALUES (?, ?)",
                               (team._digest(token), self.invite_expiry))
        async with self.client() as member:
            payload = {"token": token, "password": PASSWORD}
            accepted = await member.post("/api/team/accept-invitation", json={**payload, "handle": "legacy"})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            replay = await member.post("/api/team/accept-invitation", json={**payload, "handle": "second"})
            self.assertEqual(replay.status_code, 400)

    async def test_comfy_job_history_and_status_are_member_scoped(self):
        backend_url = "http://comfy.example"
        backend = AsyncMock()
        backend.get.return_value = httpx.Response(200, json={"comfy-id": {"outputs": {"1": {"images": [{"filename": "result.png"}]}}}})
        for name, value in {
            "get_base_workflow": {}, "get_best_backend": backend_url, "get_backend_client": backend,
            "get_comfy_servers": [], "backend_inventory": {}, "resolve_models": {"workflow": {}, "models": [], "errors": []},
            "submit_prompt": {"prompt_id": "comfy-id"},
        }.items():
            self.patch(patch.object(generation_v2, name, return_value=value))
        self.patch(patch.object(outputs, "get_backend_client", return_value=backend))
        self.patch(patch.object(status, "get_backend_client", return_value=backend))

        async with self.client() as owner, self.client() as alice, self.client() as bob, self.client() as operator:
            await self.login(owner)
            alice_id = await self.add_user(owner, alice, "alice")
            bob_id = await self.add_user(owner, bob, "bob")
            operator_id = await self.add_user(owner, operator, "staff", "operator")
            with patch("app.main.emit_terminal_event") as terminal_event:
                generated = await alice.post("/api/generate", data={"tool_id": "comfy"})
            terminal_event.assert_any_call("generation", "queued", "alice queued a generation")
            self.assertEqual(generated.status_code, 200, generated.text)
            job_id = generated.json()["prompt_id"]
            self.assertNotEqual(job_id, "comfy-id")
            self.assertEqual(database.get_generation_record("comfy-id")["user_id"], alice_id)
            params = {"prompt_id": job_id, "client_id": "ignored"}
            self.assertIn('"completed"', (await alice.get("/api/status", params=params)).text)
            self.assertEqual((await alice.get("/api/outputs", params=params)).json()["count"], 1)
            history = (await alice.get("/api/team/generations")).json()["jobs"]
            self.assertEqual([(item["id"], item["status"]) for item in history], [(job_id, "completed")])
            for other in (bob, owner, operator):
                self.assertEqual((await other.get("/api/status", params=params)).status_code, 404)
                self.assertEqual((await other.get("/api/outputs", params=params)).status_code, 404)
                self.assertEqual((await other.get("/api/team/generations")).json()["jobs"], [])

            profile_url = f"/api/team/users/{alice_id}"
            budget_url = f"/api/team/budgets/members/{alice_id}"
            self.assertEqual((await owner.put("/api/team/budgets/workspace", json={"usd": "5"})).status_code, 200)
            self.assertEqual((await operator.put(budget_url, json={"usd": "3.25"})).status_code, 200)
            for staff in (owner, operator):
                profile = await staff.get(profile_url)
                self.assertEqual(profile.status_code, 200, profile.text)
                details = profile.json()
                self.assertEqual(details["user"]["handle"], "alice")
                self.assertEqual(details["usage"]["limit_micros"], 3_250_000)
                self.assertEqual(details["configured_limit_micros"], 3_250_000)
                self.assertEqual(details["jobs"], [{key: history[0][key] for key in (
                    "tool_id", "provider", "created", "output_type", "status",
                )}])
                self.assertTrue(details["permissions"]["reset"])
                self.assertEqual(details["permissions"]["role"], staff is owner)
            self.assertEqual((await owner.get(f"/api/team/users/{bob_id}")).json()["jobs"], [])
            accounts = (await owner.get("/api/team/spend")).json()["members"]
            self.assertEqual({account["handle"]: account["generation_count"] for account in accounts},
                             {"alice": 1, "bob": 0, "owner": 0, "staff": 0})
            self.assertEqual((await owner.get(f"/api/team/users/{self.owner_id}")).json()["permissions"],
                             {"budget": True, "role": False, "enable": False, "reset": False, "remove": False})
            self.assertEqual((await operator.get(f"/api/team/users/{self.owner_id}")).status_code, 403)
            self.assertEqual((await operator.get(f"/api/team/users/{operator_id}")).status_code, 200)
            self.assertEqual((await alice.get(profile_url)).status_code, 403)
            self.assertEqual((await bob.get(profile_url)).status_code, 403)

    async def test_team_lan_http_sign_in_requires_opt_in_and_a_private_connection(self):
        self.patch(patch.object(access, "_machine_hostnames", return_value={"team.example"}))
        address = "http://team.example"
        async with self.client(address) as owner:
            self.assertEqual((await owner.get("/team")).status_code, 403)
            with patch.dict("os.environ", {"ORANGE_RUNNING_LAN_HTTP": "1"}):
                self.assertEqual((await owner.get("/team")).status_code, 200)
                self.assertEqual((await owner.get("/api/admin/usage")).status_code, 401)
                credentials = {"handle": "owner", "password": PASSWORD}
                cross_site = await owner.post("/api/team/login", json=credentials, headers={"Origin": "http://other.example"})
                self.assertEqual(cross_site.status_code, 403)
                login = await owner.post("/api/team/login", json=credentials)
                self.assertEqual(login.status_code, 200, login.text)
                self.assertIn("orange_team", login.headers["set-cookie"])
                self.assertNotIn("Secure", login.headers["set-cookie"])
                self.assertEqual((await owner.get("/admin")).status_code, 200)
                self.assertEqual((await owner.get("/api/admin/usage")).status_code, 200)
                async with self.client(address, peer="198.51.100.25") as public, self.client("http://other.example") as unknown:
                    self.assertEqual((await public.get("/team")).status_code, 403)
                    self.assertEqual((await unknown.get("/team")).status_code, 403)
            self.assertEqual((await owner.get("/admin")).status_code, 403)

    async def test_team_cloud_budget_reserves_before_dispatch_and_reconciles(self):
        self.patch(patch.object(media_providers, "validate_api_tool", return_value=SimpleNamespace(id="image", output="image", prompt_limit=1000)))
        self.patch(patch.object(media_providers.config, "ready", return_value=True))
        schedule = self.patch(patch.object(media_jobs.job_manager, "_schedule"))
        self.patch(patch.object(media_jobs, "credential", return_value="fake-provider-key"))
        self.patch(patch.object(media_jobs.job_manager, "slots", asyncio.Semaphore(2)))
        png = BytesIO()
        Image.new("RGB", (4, 4), "orange").save(png, "PNG")
        adapter = SimpleNamespace(managed_jobs=True, submit=AsyncMock(return_value=ProviderResult(
            media=[Media(png.getvalue(), "image/png")], reported_cost_micros=250_000,
        )))
        self.patch(patch.dict(media_jobs.ADAPTERS, {"openai": adapter}))

        async with self.client() as owner, self.client() as operator, self.client() as member:
            await self.login(owner)
            operator_id = await self.add_user(owner, operator, "operator", "operator")
            member_id = await self.add_user(owner, member, "member")
            request = {"tool_id": "cloud", "prompt": "private text"}
            self.assertEqual((await member.post("/api/generate", data=request)).status_code, 403)
            schedule.assert_not_called()
            self.assertEqual((await owner.put("/api/team/budgets/tools/cloud", json={"usd": "0.40"})).status_code, 200)
            self.assertEqual((await member.post("/api/generate", data=request)).status_code, 402)
            self.assertEqual((await operator.put("/api/team/budgets/workspace", json={"usd": "2"})).status_code, 403)
            self.assertEqual((await owner.put("/api/team/budgets/workspace", json={"usd": "1"})).status_code, 200)
            self.assertEqual((await operator.put(f"/api/team/budgets/members/{operator_id}", json={"usd": "1"})).status_code, 403)
            member_limit = f"/api/team/budgets/members/{member_id}"
            self.assertEqual((await operator.put(member_limit, json={"usd": "1.01"})).status_code, 400)
            self.assertEqual((await operator.put(member_limit, json={"usd": "0.60"})).status_code, 200)
            created, blocked = await asyncio.gather(*(member.post("/api/generate", data=request) for _ in range(2)))
            if created.status_code != 200:
                created, blocked = blocked, created
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(blocked.status_code, 402, blocked.text)
            job_id = created.json()["prompt_id"]
            schedule.assert_called_once()
            adapter.submit.assert_not_called()
            reserved = (await member.get("/api/team/spend")).json()["own"]
            self.assertEqual(reserved["reserved_micros"], 400_000)
            self.assertEqual(reserved["remaining_micros"], 200_000)

            job_args = schedule.call_args.args
            await media_jobs.job_manager._execute(media_jobs.get_job(job_args[0]), job_args[1])
            adapter.submit.assert_awaited_once()
            settled = (await member.get("/api/team/spend")).json()["own"]
            self.assertEqual(settled["reported_micros"], 250_000)
            self.assertEqual(settled["reserved_micros"], 0)
            self.assertEqual(settled["remaining_micros"], 350_000)
            self.assertEqual(settled["blocked"], 2)
            self.assertEqual(database.get_generation_record(job_id)["user_id"], member_id)
            self.assertEqual((await member.get(f"/api/output?prompt_id={job_id}")).status_code, 200)
            self.assertEqual((await operator.get(f"/api/media?prompt_id={job_id}")).status_code, 404)
            self.assertEqual((await operator.post(f"/api/jobs/{job_id}/retry-download")).status_code, 404)

    async def test_ledger_serializes_workspace_reservations_and_recovers_unqueued(self):
        invite = team.invite(self.owner_id, "member", self.invite_expiry)
        ids = [team.current_user(team.accept_invitation(invite["token"], PASSWORD, handle))["id"]
               for handle in ("first", "second")]
        budgets.set_workspace_limit(self.owner_id, 500_000)
        budgets.set_tool_price(self.owner_id, CLOUD_TOOL, 300_000)

        async def reserve(index, user_id):
            job_id = f"api-{index:032x}"
            try:
                await asyncio.to_thread(budgets.reserve_cloud_job, job_id, user_id, CLOUD_TOOL, "image")
                return job_id
            except HTTPException as error:
                self.assertEqual(error.status_code, 402)
                return None

        jobs = [value for value in await asyncio.gather(*(reserve(i, user) for i, user in enumerate(ids))) if value]
        self.assertEqual(len(jobs), 1)
        report = budgets.report({"id": self.owner_id, "role": "owner"}, [])
        self.assertEqual(report["workspace"]["reserved_micros"], 300_000)
        await media_jobs.MediaJobManager().start()
        report = budgets.report({"id": self.owner_id, "role": "owner"}, [])
        self.assertEqual(report["workspace"]["remaining_micros"], 500_000)
        job_id = await reserve(3, ids[0])
        budgets.mark_dispatched(job_id)
        budgets.record_job_status(job_id, "delivery_failed", terminal=True)
        budgets.record_job_status(job_id, "processing")
        budgets.record_job_status(job_id, "completed", terminal=True)
        report = budgets.report({"id": self.owner_id, "role": "owner"}, [])
        self.assertEqual(report["workspace"]["estimated_micros"], 300_000)
        self.assertEqual(report["workspace"]["remaining_micros"], 200_000)

    async def test_open_status_stream_stops_when_the_session_is_revoked(self):
        token = team.login("owner", PASSWORD)
        request = SimpleNamespace(url=SimpleNamespace(scheme="http"), cookies={team.SESSION_COOKIE: token})
        closed = asyncio.Event()

        async def job_events():
            try:
                yield "first update"
                await asyncio.Event().wait()
            finally:
                closed.set()

        with patch.object(team, "STREAM_SESSION_CHECK_SECONDS", 0.02):
            stream = team.guard_events(request, job_events())
            self.assertEqual(await anext(stream), "first update")
            team.logout(token)
            with self.assertRaises(StopAsyncIteration):
                await asyncio.wait_for(anext(stream), timeout=1)
            self.assertTrue(closed.is_set())

    def test_provider_cost_ingestion_ignores_unrecognized_fields(self):
        payload = {"data": [{"b64_json": "aGVsbG8="}], "usage": {"cost": 0.01234512, "total_tokens": 1, "other": "private"}}
        result = raster_result(payload)
        self.assertEqual(result.reported_cost_micros, 12_346)
        self.assertEqual(result.usage, {"total_tokens": 1})
