import unittest

from app.api.admin import _html_safe_log


class AdminSafetyTests(unittest.TestCase):
    def test_usage_prompt_is_html_escaped(self):
        row = {
            "prompt": '<img src=x onerror="alert(1)">',
            "client_ip": "127.0.0.1",
            "tool_id": "z-image",
        }

        safe = _html_safe_log(row)

        self.assertNotIn("<img", safe["prompt"])
        self.assertIn("&lt;img", safe["prompt"])
        self.assertIn("&quot;", safe["prompt"])
        self.assertEqual(row["prompt"], '<img src=x onerror="alert(1)">')


if __name__ == "__main__":
    unittest.main()
