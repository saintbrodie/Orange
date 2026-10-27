import io
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from scripts.verify_comfyui_runtime import prepare_workflow, promotion_ready, smoke


class PromotionTests(unittest.TestCase):
    @patch("scripts.verify_comfyui_runtime.required_pack_ids", return_value={"image", "edit"})
    def test_requires_real_smoke_and_complete_pack_coverage(self, _):
        report = {"passed": True, "tools": [
            {"id": "image", "preflightPassed": True, "smokePassed": True},
        ]}
        self.assertFalse(promotion_ready(report))
        report["tools"].append({"id": "edit", "preflightPassed": True, "smokePassed": False})
        self.assertFalse(promotion_ready(report))
        report["tools"][1]["smokePassed"] = True
        self.assertTrue(promotion_ready(report))
        report["passed"] = False
        self.assertFalse(promotion_ready(report))

    def test_test_inputs_do_not_mutate_original_workflow(self):
        original = {"1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}}}
        prepared = prepare_workflow(original, {"image": {"nodeId": "1", "field": "image"}}, "test.png")
        self.assertEqual(prepared["1"]["inputs"]["image"], "test.png")
        self.assertEqual(original["1"]["inputs"]["image"], "old.png")


class SmokeTests(unittest.IsolatedAsyncioTestCase):
    @patch("scripts.verify_comfyui_runtime.submit_prompt", new_callable=AsyncMock)
    async def test_success_requires_fetchable_decodable_image(self, submit):
        submit.return_value = {"prompt_id": "test"}
        history = Mock()
        history.json.return_value = {"test": {
            "status": {"completed": True},
            "outputs": {"1": {"images": [{"filename": "test.png"}]}},
        }}
        data = io.BytesIO()
        Image.new("RGB", (16, 16)).save(data, "PNG")
        media = Mock(content=data.getvalue())
        client = Mock(get=AsyncMock(side_effect=[history, media]))
        result = await smoke(client, "http://localhost", {}, 10)
        self.assertEqual(result["bytes"], len(data.getvalue()))
        media.raise_for_status.assert_called_once()

    @patch("scripts.verify_comfyui_runtime.submit_prompt", new_callable=AsyncMock)
    async def test_execution_failure_cannot_pass(self, submit):
        submit.return_value = {"prompt_id": "test"}
        response = Mock()
        response.json.return_value = {"test": {"status": {"status_str": "error"}}}
        client = Mock(get=AsyncMock(return_value=response))
        with self.assertRaisesRegex(ValueError, "failed"):
            await smoke(client, "http://localhost", {}, 10)

    @patch("scripts.verify_comfyui_runtime.submit_prompt", new_callable=AsyncMock)
    async def test_completed_without_output_cannot_pass(self, submit):
        submit.return_value = {"prompt_id": "test"}
        response = Mock()
        response.json.return_value = {"test": {"status": {"completed": True}, "outputs": {}}}
        client = Mock(get=AsyncMock(return_value=response))
        with self.assertRaisesRegex(ValueError, "without an image"):
            await smoke(client, "http://localhost", {}, 10)


if __name__ == "__main__":
    unittest.main()
