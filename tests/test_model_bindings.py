import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException

from app.api import admin, generation_v2, preflight as preflight_api
from app.core import model_bindings as models
from app.core.preflight import _check_backend


def graph(filename="old/Wan/wan_2.1_vae.safetensors"):
    return {"58": {"class_type": "VAELoader", "inputs": {"vae_name": filename}}}


def info(*paths):
    return {"VAELoader": {"input": {"required": {"vae_name": ["COMBO", {"options": list(paths)}]}}}}


class ModelBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "model-bindings.json"
        self.store_patch = patch.object(models, "BINDINGS_PATH", str(self.store))
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.tmp.cleanup()

    def test_unique_filename_resolves_recursive_inventory_without_mutating_workflow(self):
        workflow = graph()
        original = copy.deepcopy(workflow)
        result = models.resolve_models(workflow, info("nested\\models\\wan_2.1_vae.safetensors"), "http://one")
        self.assertEqual(result["workflow"]["58"]["inputs"]["vae_name"], "nested\\models\\wan_2.1_vae.safetensors")
        self.assertEqual(result["models"][0]["reason"], "filename")
        self.assertEqual(workflow, original)
        self.assertFalse(self.store.exists())

    def test_exact_normalized_path_wins_over_other_same_filename(self):
        result = models.resolve_models(graph("a/wan_2.1_vae.safetensors"), info("b/wan_2.1_vae.safetensors", "a\\wan_2.1_vae.safetensors"), "http://one")
        self.assertEqual(result["models"][0]["resolved"], "a\\wan_2.1_vae.safetensors")

    def test_ambiguity_requires_choice_and_bindings_are_backend_specific(self):
        inventory = info("a/wan_2.1_vae.safetensors", "b/wan_2.1_vae.safetensors")
        workflow = graph()
        unresolved = models.resolve_models(workflow, inventory, "HTTP://ONE:80/")
        self.assertEqual(unresolved["errors"][0]["code"], "model_ambiguous")
        ref = unresolved["models"][0]
        models.save_binding("HTTP://ONE:80/", ref, ref["options"][1])
        first = models.resolve_models(workflow, inventory, "http://one")
        second = models.resolve_models(workflow, inventory, "http://two")
        self.assertEqual(first["models"][0]["resolved"], "b/wan_2.1_vae.safetensors")
        self.assertEqual(first["models"][0]["reason"], "binding")
        self.assertEqual(second["errors"][0]["code"], "model_ambiguous")
        models.save_binding("http://two", ref, ref["options"][0])
        self.assertEqual(models.resolve_models(workflow, inventory, "http://two")["models"][0]["resolved"], "a/wan_2.1_vae.safetensors")
        self.assertEqual(json.loads(self.store.read_text())["version"], 1)
        models.save_binding("http://one", ref, None)
        self.assertTrue(models.resolve_models(workflow, inventory, "http://one")["errors"])

    def test_stale_binding_relocates_unique_file_but_does_not_guess_duplicates(self):
        ref = models.model_references(graph(), info("a/wan_2.1_vae.safetensors"))[0]
        models.save_binding("http://one", ref, ref["options"][0])
        result = models.resolve_models(graph(), info("moved/wan_2.1_vae.safetensors"), "http://one")
        self.assertEqual(result["models"][0]["resolved"], "moved/wan_2.1_vae.safetensors")
        self.assertTrue(result["models"][0]["stale_binding"])
        self.assertEqual(models.saved_binding("http://one", "vae", ref["filename"]), ref["options"][0])
        result = models.resolve_models(graph(), info("b/wan_2.1_vae.safetensors", "c/wan_2.1_vae.safetensors"), "http://one")
        self.assertEqual(result["errors"][0]["code"], "model_ambiguous")

    def test_missing_model_never_substitutes_precision_or_similar_names(self):
        result = models.resolve_models(graph("model_bf16.safetensors"), info("model_fp8.safetensors", "model_bf16_v2.safetensors"), "http://one")
        self.assertEqual(result["errors"][0]["code"], "model_missing")
        with self.assertRaises(ValueError):
            models.save_binding("http://one", result["models"][0], "model_fp8.safetensors")

    def test_categories_are_isolated_and_non_model_enums_and_mapped_inputs_are_ignored(self):
        workflow = graph("model.safetensors")
        inventory = info("a/model.safetensors", "b/model.safetensors")
        ref = models.model_references(workflow, inventory)[0]
        models.save_binding("http://one", ref, ref["options"][0])
        workflow["2"] = {"class_type": "LoraLoader", "inputs": {"lora_name": "model.safetensors"}}
        inventory["LoraLoader"] = {"input": {"required": {"lora_name": [["a/model.safetensors", "b/model.safetensors"]]}}}
        workflow["3"] = {"class_type": "LoadImage", "inputs": {"image": "reference.png"}}
        inventory["LoadImage"] = {"input": {"required": {"image": [["sub/reference.png"]]}}}
        result = models.resolve_models(workflow, inventory, "http://one")
        self.assertEqual(len(result["models"]), 2)
        self.assertEqual(result["errors"][0]["node_id"], "2")
        self.assertEqual(result["workflow"]["3"], workflow["3"])
        self.assertEqual(models.model_references(graph(), info(), {"image": {"nodeId": "58", "field": "vae_name"}}), [])


class InventoryAndApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store_patch = patch.object(models, "BINDINGS_PATH", str(Path(self.tmp.name) / "bindings.json"))
        self.store_patch.start()
        models._inventory.clear()

    async def asyncTearDown(self):
        models._inventory.clear()
        self.store_patch.stop()
        self.tmp.cleanup()

    async def test_inventory_cache_refresh_and_expiry(self):
        calls = []
        def respond(request):
            calls.append(str(request.url))
            return httpx.Response(200, json=info(f"folder{len(calls)}/wan_2.1_vae.safetensors"))
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            first = await models.backend_inventory(client, "http://one/")
            self.assertEqual(await models.backend_inventory(client, "http://one"), first)
            self.assertNotEqual(await models.backend_inventory(client, "http://one", refresh=True), first)
            with patch.object(models, "INVENTORY_TTL", -1):
                await models.backend_inventory(client, "http://one")
            models.invalidate_inventory("http://one/")
            await models.backend_inventory(client, "http://one")
        self.assertEqual(len(calls), 4)

    async def test_preflight_resolves_same_graph_for_two_backends(self):
        def respond(request):
            return httpx.Response(200, json=info(f"{request.url.host}/wan_2.1_vae.safetensors"))
        workflow = graph()
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            for name in ("one", "two"):
                result = await _check_backend(client, {"url": f"http://{name}"}, workflow, {}, set())
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["models"][0]["resolved"], f"{name}/wan_2.1_vae.safetensors")
                self.assertFalse(result["warnings"])
        self.assertEqual(workflow, graph())

    async def test_binding_api_checks_backend_inventory_and_never_writes_workflow(self):
        payload = {"backendUrl": "http://one", "workflowFile": "custom.json", "nodeId": "58",
                   "field": "vae_name", "path": "a/wan_2.1_vae.safetensors"}
        workflow = graph()
        with patch.object(preflight_api, "get_comfy_servers", return_value=[{"url": "http://one"}]), \
             patch.object(preflight_api, "get_base_workflow", return_value=workflow), \
             patch.object(preflight_api, "backend_inventory", return_value=info("a/wan_2.1_vae.safetensors", "b/wan_2.1_vae.safetensors")), \
             patch.object(preflight_api.backend_manager, "invalidate_compatibility") as invalidate:
            result = await preflight_api.update_model_binding(payload, _=True)
            self.assertTrue(result["saved"])
            invalidate.assert_called_once_with("http://one")
            self.assertEqual(workflow, graph())
            with self.assertRaises(HTTPException) as error:
                await preflight_api.update_model_binding({**payload, "path": "other_precision.safetensors"}, _=True)
            self.assertEqual(error.exception.status_code, 400)
            with self.assertRaises(HTTPException) as error:
                await preflight_api.update_model_binding({**payload, "backendUrl": "http://unconfigured"}, _=True)
            self.assertEqual(error.exception.status_code, 404)

    async def test_authenticated_binding_preflight_and_generation_share_resolution(self):
        app = FastAPI()
        app.include_router(preflight_api.router)
        app.include_router(generation_v2.router)
        workflow = graph()
        workflows = Path(self.tmp.name) / "workflows"
        workflows.mkdir()
        source = workflows / "custom.json"
        source.write_text(json.dumps(workflow), encoding="utf-8")
        original_bytes = source.read_bytes()
        inventory = info("a/wan_2.1_vae.safetensors", "b/wan_2.1_vae.safetensors")
        prompts = []
        def backend(request):
            if request.url.path == "/object_info":
                return httpx.Response(200, json=inventory)
            if request.url.path == "/prompt":
                prompts.append(json.loads(request.content)["prompt"])
                return httpx.Response(200, json={"prompt_id": "bound-generation"})
            raise AssertionError(str(request.url))
        client_type = httpx.AsyncClient
        api_client = client_type(transport=httpx.ASGITransport(app=app), base_url="http://orange")
        backend_client = client_type(transport=httpx.MockTransport(backend))
        servers = [{"url": "http://one"}, {"url": "http://two"}]
        with (
            patch.object(admin, "load_config", return_value={"adminKey": "test-key"}),
            patch.object(preflight_api, "PROJECT_ROOT", self.tmp.name),
            patch.object(preflight_api, "get_base_workflow", return_value=workflow),
            patch.object(preflight_api, "get_comfy_servers", return_value=servers),
            patch.object(generation_v2, "get_base_workflow", return_value=workflow),
            patch.object(generation_v2, "get_tool_settings", return_value={"workflowFile": "custom.json", "nodeMapping": {}}),
            patch.object(generation_v2, "load_config", return_value={}),
            patch.object(generation_v2, "get_comfy_servers", return_value=servers),
            patch.object(generation_v2, "get_best_backend", return_value="http://one"),
            patch.object(generation_v2, "get_backend_client", return_value=backend_client),
            patch.object(generation_v2, "log_usage"),
            patch.object(httpx, "AsyncClient", side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(backend), **kwargs)),
        ):
            async with api_client, backend_client:
                payload = {"backendUrl": "http://one", "workflowFile": "custom.json", "nodeId": "58",
                           "field": "vae_name", "path": "b/wan_2.1_vae.safetensors"}
                self.assertEqual((await api_client.post("/api/admin/workflows/model-binding", json=payload)).status_code, 401)
                response = await api_client.post("/api/admin/workflows/model-binding", json=payload,
                                                 headers={"Authorization": "Bearer test-key"})
                self.assertEqual(response.status_code, 200, response.text)
                checked = await api_client.post("/api/admin/workflows/preflight", json={"workflowFile": "custom.json", "nodeMapping": {}},
                                                headers={"Authorization": "Bearer test-key"})
                self.assertEqual(checked.status_code, 200, checked.text)
                one, two = checked.json()["backends"]
                self.assertTrue(one["routing_compatible"])
                self.assertFalse(two["routing_compatible"])
                response = await api_client.post("/api/generate", data={"tool_id": "custom"})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["prompt_id"], "bound-generation")
        self.assertEqual(prompts[0]["58"]["inputs"]["vae_name"], "b/wan_2.1_vae.safetensors")
        self.assertEqual(workflow, graph())
        self.assertEqual(source.read_bytes(), original_bytes)
