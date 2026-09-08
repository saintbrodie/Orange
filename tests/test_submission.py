import unittest

import httpx

from app.core.submission import SubmissionFailure, submit_prompt, upload_image_bytes


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def post(self, *args, **kwargs):
        if self.error:
            raise self.error
        return self.response


def _response(status: int, json_data=None, text: str = ""):
    request = httpx.Request("POST", "http://backend/prompt")
    if json_data is not None:
        return httpx.Response(status, json=json_data, request=request)
    return httpx.Response(status, text=text, request=request)


class SubmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_failure_is_safe_to_retry(self):
        client = _FakeClient(error=httpx.ConnectError("no route"))
        with self.assertRaises(SubmissionFailure) as ctx:
            await submit_prompt(client, "http://backend", {"prompt": {}})
        self.assertTrue(ctx.exception.retryable)
        self.assertTrue(ctx.exception.mark_backend_failed)

    async def test_read_timeout_is_not_retried_to_avoid_duplicate_job(self):
        request = httpx.Request("POST", "http://backend/prompt")
        client = _FakeClient(error=httpx.ReadTimeout("lost response", request=request))
        with self.assertRaises(SubmissionFailure) as ctx:
            await submit_prompt(client, "http://backend", {"prompt": {}})
        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("may still have started", ctx.exception.public_message.lower())

    async def test_workflow_rejection_does_not_mark_backend_unhealthy(self):
        client = _FakeClient(response=_response(400, text="bad node"))
        with self.assertRaises(SubmissionFailure) as ctx:
            await submit_prompt(client, "http://backend", {"prompt": {}})
        self.assertFalse(ctx.exception.retryable)
        self.assertFalse(ctx.exception.mark_backend_failed)
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_backend_500_is_retryable(self):
        client = _FakeClient(response=_response(503, text="temporarily unavailable"))
        with self.assertRaises(SubmissionFailure) as ctx:
            await submit_prompt(client, "http://backend", {"prompt": {}})
        self.assertTrue(ctx.exception.retryable)
        self.assertTrue(ctx.exception.mark_backend_failed)

    async def test_prompt_id_is_required_for_success(self):
        client = _FakeClient(response=_response(200, json_data={"number": 1}))
        with self.assertRaises(SubmissionFailure) as ctx:
            await submit_prompt(client, "http://backend", {"prompt": {}})
        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_image_upload_timeout_can_retry_safely(self):
        request = httpx.Request("POST", "http://backend/upload/image")
        client = _FakeClient(error=httpx.ReadTimeout("timeout", request=request))
        with self.assertRaises(SubmissionFailure) as ctx:
            await upload_image_bytes(client, "http://backend", "x.png", b"png", "image/png")
        self.assertTrue(ctx.exception.retryable)


if __name__ == "__main__":
    unittest.main()
