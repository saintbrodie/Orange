import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.core import database


class GenerationStatusDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tempdir.name, "usage.db")
        self.path_patch = patch.object(database, "DB_PATH", self.db_path)
        self.path_patch.start()
        database.init_db()

    def tearDown(self):
        self.path_patch.stop()
        self.tempdir.cleanup()

    def test_generation_starts_queued(self):
        database.log_usage(
            "127.0.0.1",
            "test-tool",
            "hello",
            prompt_id="prompt-1",
            backend_url="http://server:8188",
        )

        row = database.get_generation_record("prompt-1")

        self.assertEqual(row["status"], "queued")
        self.assertIsNone(row["error"])
        self.assertEqual(row["backend_url"], "http://server:8188")

    def test_status_and_technical_error_are_updated(self):
        database.log_usage("127.0.0.1", "test-tool", prompt_id="prompt-2")
        database.update_usage_status("prompt-2", "error", "custom node exploded")

        row = database.get_generation_record("prompt-2")

        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "custom node exploded")

    def test_technical_error_is_bounded(self):
        database.log_usage("127.0.0.1", "test-tool", prompt_id="prompt-3")
        database.update_usage_status("prompt-3", "error", "x" * 9000)

        row = database.get_generation_record("prompt-3")

        self.assertEqual(len(row["error"]), 8000)

    def _replace_with_legacy_usage_table(self):
        os.remove(self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE usage (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, client_ip TEXT, tool_id TEXT, prompt TEXT)"
            )

    def test_init_db_migrates_legacy_usage_table(self):
        self._replace_with_legacy_usage_table()

        database.init_db()
        database.log_usage("127.0.0.1", "test-tool", prompt_id="prompt-4")
        row = database.get_generation_record("prompt-4")

        self.assertEqual(row["status"], "queued")
        self.assertIn("backend_url", row)
        self.assertIn("error", row)

    def test_logging_self_repairs_legacy_database_after_live_restore(self):
        self._replace_with_legacy_usage_table()

        database.log_usage("127.0.0.1", "test-tool", prompt_id="prompt-5")
        database.update_usage_status("prompt-5", "completed")
        row = database.get_generation_record("prompt-5")

        self.assertEqual(row["status"], "completed")
        self.assertIn("backend_url", row)
        self.assertIn("error", row)


if __name__ == "__main__":
    unittest.main()
