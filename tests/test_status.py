import unittest

from app.api.status import _history_record_state, _websocket_url


class StatusParsingTests(unittest.TestCase):
    def test_completed_history_status_is_completed(self):
        state, error = _history_record_state(
            {"status": {"completed": True, "status_str": "success", "messages": []}}
        )

        self.assertEqual(state, "completed")
        self.assertIsNone(error)

    def test_outputs_are_completion_fallback(self):
        state, error = _history_record_state({"outputs": {"10": {"images": [{"filename": "x.png"}]}}})

        self.assertEqual(state, "completed")
        self.assertIsNone(error)

    def test_execution_error_is_not_treated_as_completion(self):
        state, error = _history_record_state(
            {
                "status": {
                    "completed": False,
                    "status_str": "error",
                    "messages": [
                        [
                            "execution_error",
                            {
                                "node_id": "42",
                                "node_type": "BrokenNode",
                                "exception_type": "RuntimeError",
                                "exception_message": "model file missing",
                            },
                        ]
                    ],
                }
            }
        )

        self.assertEqual(state, "error")
        self.assertIn("model file missing", error)
        self.assertIn("BrokenNode", error)

    def test_execution_interrupted_is_reported(self):
        state, error = _history_record_state(
            {
                "status": {
                    "messages": [
                        ["execution_interrupted", {"prompt_id": "abc", "node_id": "7"}],
                    ]
                }
            }
        )

        self.assertEqual(state, "interrupted")
        self.assertIn("abc", error)

    def test_status_error_without_message_is_error(self):
        state, error = _history_record_state(
            {"status": {"completed": False, "status_str": "error", "messages": []}}
        )

        self.assertEqual(state, "error")
        self.assertIn("status_str", error)

    def test_websocket_url_preserves_reverse_proxy_path(self):
        url = _websocket_url("https://orange-host.example/comfy", "client id")

        self.assertEqual(url, "wss://orange-host.example/comfy/ws?clientId=client+id")

    def test_websocket_url_uses_ws_for_http(self):
        url = _websocket_url("http://127.0.0.1:8188", "abc")

        self.assertEqual(url, "ws://127.0.0.1:8188/ws?clientId=abc")


if __name__ == "__main__":
    unittest.main()
