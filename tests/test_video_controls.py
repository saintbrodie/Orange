import copy
import io
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.requests import Request
from starlette.datastructures import Headers

from app.api import generation_v2
from app.core.config_validation import validate_config
from app.core.public_config import build_public_config
from app.core.video_controls import apply_duration, select_input_variant, tool_variants

ROOT = Path(__file__).resolve().parents[1]


def tool_and_workflow():
    tool = json.loads((ROOT / "workflow-packs/ltx-2.5-t2v/manifest.json").read_text())["tool"]
    workflow = json.loads((ROOT / "workflows/defaults" / tool["workflowFile"]).read_text())
    return tool, workflow


class VideoControlTests(unittest.TestCase):
    def test_lengths_keep_audio_and_video_in_sync(self):
        tool, workflow = tool_and_workflow()
        for seconds, frames in [(2, 49), (4, 97), (12, 289)]:
            apply_duration(workflow, tool, seconds)
            self.assertEqual(workflow["video_frames"]["inputs"]["value"], frames)
            self.assertEqual((frames - 1) % 8, 0)
            self.assertEqual(workflow["405:356"]["inputs"]["length"], workflow["405:366"]["inputs"]["frames_number"])
        for invalid in (3, -1, float("nan"), float("inf"), True, 999):
            with self.assertRaises(ValueError):
                apply_duration(workflow, tool, invalid)

    def test_first_frame_selects_a_separate_graph_only_when_uploaded(self):
        tool, workflow = tool_and_workflow()
        self.assertNotIn("image", select_input_variant(tool, False)["nodeMapping"])
        selected = select_input_variant(tool, True)
        self.assertEqual(selected["workflowFile"], "video_ltx_2_5_i2v.json")
        self.assertIn("image", selected["nodeMapping"])
        self.assertEqual(len(tool_variants(tool)), 2)
        self.assertNotIn("image", tool["nodeMapping"])

    def test_public_controls_do_not_expose_alternate_workflow(self):
        tool, _ = tool_and_workflow()
        public = build_public_config({"tools": [tool]})["tools"][0]
        self.assertTrue(public["firstFrame"])
        self.assertEqual(public["duration"], {"default": 4, "options": [2, 4, 6, 8, 10, 12]})
        self.assertNotIn("imageVariant", public)

    def test_invalid_duration_and_nested_variant_are_rejected(self):
        tool, _ = tool_and_workflow()
        tool["duration"]["options"] = [True]
        tool["imageVariant"]["imageVariant"] = {}
        result = validate_config({"tools": [tool]})
        self.assertTrue(any(e["code"] == "duration_invalid" for e in result["errors"]))
        self.assertTrue(any(e["code"] == "image_variant_invalid" for e in result["errors"]))


class VideoSubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def submit(self, with_image=False, duration=2):
        tool, _ = tool_and_workflow()
        image = None
        if with_image:
            data = io.BytesIO()
            Image.new("RGB", (64, 64), "orange").save(data, "PNG")
            data.seek(0)
            image = UploadFile(filename="first.png", file=data, headers=Headers({"content-type": "image/png"}))
        submit = AsyncMock(return_value={"prompt_id": "test-job"})
        request = Request({"type": "http", "method": "POST", "path": "/api/generate", "headers": [], "client": ("127.0.0.1", 1)})
        def load_workflow(filename):
            return json.loads((ROOT / "workflows/defaults" / filename).read_text())
        with (patch.object(generation_v2, "get_tool_settings", return_value=tool),
              patch.object(generation_v2, "get_base_workflow", side_effect=load_workflow),
              patch.object(generation_v2, "_prepare_asset_payloads", return_value=([], {})),
              patch.object(generation_v2, "_stage_assets", new_callable=AsyncMock),
              patch.object(generation_v2, "load_config", return_value={}),
              patch.object(generation_v2, "get_best_backend", AsyncMock(return_value="http://comfy")),
              patch.object(generation_v2, "get_backend_client", AsyncMock(return_value=object())),
              patch.object(generation_v2, "upload_image_bytes", AsyncMock(return_value="uploaded.png")) as upload,
              patch.object(generation_v2, "submit_prompt", submit),
              patch.object(generation_v2, "get_comfy_servers", return_value=[{"url": "http://comfy", "priority": 1}]),
              patch.object(generation_v2, "increment_active"), patch.object(generation_v2, "decrement_active"),
              patch.object(generation_v2, "report_backend_success"), patch.object(generation_v2, "log_usage")):
            await generation_v2.generate_v2(request, tool_id=tool["id"], prompt="A cat looks outside", aspect_ratio="3:2", image=image, image2=None, duration=duration)
        return submit.call_args.args[2]["prompt"], upload

    async def test_text_only_request_needs_no_image(self):
        workflow, upload = await self.submit()
        self.assertNotIn("first_frame", workflow)
        self.assertEqual(workflow["video_frames"]["inputs"]["value"], 49)
        upload.assert_not_awaited()

    async def test_first_frame_upload_is_used_by_both_sampling_stages(self):
        workflow, upload = await self.submit(with_image=True, duration=6)
        upload.assert_awaited_once()
        self.assertEqual(workflow["first_frame"]["inputs"]["image"], "uploaded.png")
        self.assertEqual(workflow["video_frames"]["inputs"]["value"], 145)
        self.assertEqual(workflow["405:377"]["inputs"]["video_latent"], ["first_frame_stage1", 0])
        self.assertEqual(workflow["405:340"]["inputs"]["video_latent"], ["first_frame_stage2", 0])

    async def test_unsupported_duration_is_rejected_before_submission(self):
        with self.assertRaises(HTTPException) as caught:
            await self.submit(duration=999)
        self.assertEqual(caught.exception.status_code, 400)
