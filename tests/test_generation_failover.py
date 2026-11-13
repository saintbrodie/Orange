import unittest
import copy
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from app.api import generation_v2
from app.core.submission import SubmissionFailure


def _request():
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/generate",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
    )


class GenerationFailoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_resolution_skips_ambiguous_backend_before_upload_or_submit(self):
        original = {"1": {"class_type": "VAELoader", "inputs": {"vae_name": "old/model.safetensors"}}}
        submitted = []

        async def inventory(_client, url, **_kwargs):
            paths = ["a/model.safetensors", "b/model.safetensors"] if url == "http://one" else ["vae/model.safetensors"]
            return {"VAELoader": {"input": {"required": {"vae_name": [paths]}}}}

        async def submit(_client, url, payload):
            submitted.append((url, copy.deepcopy(payload["prompt"])))
            return {"prompt_id": "resolved"}

        with (
            patch.object(generation_v2, "get_tool_settings", return_value={"workflowFile": "custom.json", "nodeMapping": {}}),
            patch.object(generation_v2, "get_base_workflow", return_value=original),
            patch.object(generation_v2, "_prepare_asset_payloads", return_value=([], {})),
            patch.object(generation_v2, "_stage_assets", AsyncMock()) as stage,
            patch.object(generation_v2, "load_config", return_value={}),
            patch.object(generation_v2, "get_comfy_servers", return_value=[]),
            patch.object(generation_v2, "get_best_backend", AsyncMock(side_effect=["http://one", "http://two"])),
            patch.object(generation_v2, "get_backend_client", AsyncMock(return_value=object())),
            patch.object(generation_v2, "backend_inventory", inventory),
            patch.object(generation_v2, "submit_prompt", submit),
            patch.object(generation_v2, "increment_active"), patch.object(generation_v2, "decrement_active"),
            patch.object(generation_v2, "report_backend_failure") as failed,
            patch.object(generation_v2, "report_backend_success"), patch.object(generation_v2, "log_usage"),
        ):
            result = await generation_v2.generate_v2(_request(), tool_id="test", prompt=None, aspect_ratio=None, image=None, image2=None)
        self.assertEqual(result["prompt_id"], "resolved")
        self.assertEqual(submitted, [("http://two", {"1": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/model.safetensors"}}})])
        self.assertEqual(original["1"]["inputs"]["vae_name"], "old/model.safetensors")
        stage.assert_awaited_once()
        failed.assert_not_called()

    async def test_explicit_rejection_rescans_and_retries_only_when_model_moved(self):
        original = {"1": {"class_type": "VAELoader", "inputs": {"vae_name": "model.safetensors"}}}
        paths = iter(["old/model.safetensors", "new/model.safetensors", "new/model.safetensors"])
        async def inventory(*_args, **_kwargs):
            return {"VAELoader": {"input": {"required": {"vae_name": [[next(paths)]]}}}}
        rejection = SubmissionFailure("Rejected", "ComfyUI rejected /prompt with HTTP 400: value_not_in_list", 422, True)
        submitted = []
        async def submit(_client, _url, payload):
            submitted.append(payload["prompt"]["1"]["inputs"]["vae_name"])
            if len(submitted) == 1:
                raise rejection
            return {"prompt_id": "moved"}
        with (
            patch.object(generation_v2, "get_tool_settings", return_value={"workflowFile": "custom.json", "nodeMapping": {}}),
            patch.object(generation_v2, "get_base_workflow", return_value=original),
            patch.object(generation_v2, "_prepare_asset_payloads", return_value=([], {})),
            patch.object(generation_v2, "load_config", return_value={}),
            patch.object(generation_v2, "get_comfy_servers", return_value=[]),
            patch.object(generation_v2, "get_best_backend", AsyncMock(return_value="http://one")) as choose,
            patch.object(generation_v2, "get_backend_client", AsyncMock(return_value=object())),
            patch.object(generation_v2, "backend_inventory", inventory), patch.object(generation_v2, "submit_prompt", submit),
            patch.object(generation_v2, "increment_active"), patch.object(generation_v2, "decrement_active"),
            patch.object(generation_v2, "report_backend_success"), patch.object(generation_v2, "log_usage"),
        ):
            result = await generation_v2.generate_v2(_request(), tool_id="test", prompt=None, aspect_ratio=None, image=None, image2=None)
        self.assertEqual(result["prompt_id"], "moved")
        self.assertEqual(submitted, ["old/model.safetensors", "new/model.safetensors"])
        choose.assert_awaited_once()
        self.assertEqual(original["1"]["inputs"]["vae_name"], "model.safetensors")

    async def test_backend_specific_workflow_rejection_fails_over_without_marking_server_unhealthy(self):
        tool = {
            "workflowFile": "workflow.json",
            "nodeMapping": {},
        }
        base_workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "model.safetensors"},
            }
        }
        servers = [
            {"url": "http://backend-1:8188", "priority": 1},
            {"url": "http://backend-2:8188", "priority": 2},
        ]
        rejection = SubmissionFailure(
            public_message="The workflow was rejected by this generation backend.",
            technical_message="value_not_in_list: model.safetensors is unavailable",
            status_code=422,
            retryable=True,
            mark_backend_failed=False,
        )

        seen_exclusions = []
        backend_choices = iter(["http://backend-1:8188", "http://backend-2:8188"])

        async def choose_backend(*, exclude_urls=None, compatibility_key=None):
            seen_exclusions.append(list(exclude_urls or []))
            return next(backend_choices)

        submit = AsyncMock(side_effect=[rejection, {"prompt_id": "prompt-on-backend-2"}])
        backend_client = object()

        with (
            patch.object(generation_v2, "get_tool_settings", return_value=tool),
            patch.object(generation_v2, "get_base_workflow", return_value=base_workflow),
            patch.object(generation_v2, "_prepare_asset_payloads", return_value=([], {})),
            patch.object(generation_v2, "load_config", return_value={}),
            patch.object(generation_v2, "get_comfy_servers", return_value=servers),
            patch.object(generation_v2, "get_best_backend", side_effect=choose_backend) as get_best,
            patch.object(generation_v2, "get_backend_client", AsyncMock(return_value=backend_client)),
            patch.object(generation_v2, "backend_inventory", AsyncMock(return_value={"CheckpointLoaderSimple": {
                "input": {"required": {"ckpt_name": [["model.safetensors"]]}}
            }})),
            patch.object(generation_v2, "submit_prompt", submit),
            patch.object(generation_v2, "increment_active") as increment_active,
            patch.object(generation_v2, "decrement_active"),
            patch.object(generation_v2, "report_backend_failure") as report_backend_failure,
            patch.object(generation_v2, "report_backend_success") as report_backend_success,
            patch.object(generation_v2, "log_usage") as log_usage,
        ):
            result = await generation_v2.generate_v2(
                _request(),
                tool_id="test-tool",
                prompt=None,
                aspect_ratio=None,
                image=None,
                image2=None,
            )

        self.assertEqual(result["prompt_id"], "prompt-on-backend-2")
        self.assertEqual(result["server_priority"], 2)
        self.assertEqual(
            [call.args[0] for call in increment_active.call_args_list],
            ["http://backend-1:8188", "http://backend-2:8188"],
        )
        report_backend_failure.assert_not_called()
        report_backend_success.assert_called_once_with("http://backend-2:8188")

        self.assertEqual(get_best.call_count, 2)
        self.assertEqual(seen_exclusions, [[], ["http://backend-1:8188"]])

        submit.assert_any_await(
            backend_client,
            "http://backend-1:8188",
            {"prompt": base_workflow, "client_id": result["client_id"]},
        )
        log_usage.assert_called_once()
        self.assertEqual(log_usage.call_args.kwargs["backend_url"], "http://backend-2:8188")
        self.assertEqual(log_usage.call_args.kwargs["prompt_id"], "prompt-on-backend-2")


if __name__ == "__main__":
    unittest.main()
