import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app.core.database as database


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "usage.db")
        self.original_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_active_database_uses_wal_mode(self):
        with sqlite3.connect(self.db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

    def test_backup_is_self_contained_and_contains_committed_rows(self):
        database.log_usage("127.0.0.1", "tool", "hello", prompt_id="p1")
        backup_path = os.path.join(self.temp_dir.name, "backup.db")
        database.backup_database(backup_path)

        with sqlite3.connect(backup_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            row = conn.execute("SELECT prompt_id, prompt FROM usage WHERE prompt_id = 'p1'").fetchone()
        self.assertEqual(mode.lower(), "delete")
        self.assertEqual(row, ("p1", "hello"))
        self.assertFalse(os.path.exists(backup_path + "-wal"))

    def test_restore_replaces_live_contents_and_migrates_old_schema(self):
        database.log_usage("127.0.0.1", "old-tool", "before", prompt_id="before")

        source_path = os.path.join(self.temp_dir.name, "source.db")
        with sqlite3.connect(source_path) as conn:
            conn.execute(
                """
                CREATE TABLE usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    client_ip TEXT,
                    tool_id TEXT,
                    prompt TEXT
                )
                """
            )
            conn.execute(
                "INSERT INTO usage (client_ip, tool_id, prompt) VALUES (?, ?, ?)",
                ("10.0.0.1", "restored-tool", "restored"),
            )

        previous_backup = os.path.join(self.temp_dir.name, "previous.db")
        database.restore_database(source_path, backup_path=previous_backup)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT tool_id, prompt FROM usage ORDER BY id").fetchall()
            columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)").fetchall()}
        self.assertEqual(rows, [("restored-tool", "restored")])
        self.assertTrue({"prompt_id", "backend_url", "status", "error"}.issubset(columns))

        with sqlite3.connect(previous_backup) as conn:
            old_row = conn.execute("SELECT prompt_id FROM usage WHERE prompt_id = 'before'").fetchone()
        self.assertEqual(old_row, ("before",))

    def test_invalid_database_is_rejected(self):
        invalid_path = os.path.join(self.temp_dir.name, "invalid.db")
        with open(invalid_path, "wb") as handle:
            handle.write(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            database.validate_database(invalid_path)

    def test_retention_is_disabled_by_default(self):
        with patch.dict(os.environ, {"ORANGE_USAGE_RETENTION_DAYS": "0"}):
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO usage (timestamp, client_ip, tool_id, prompt) "
                    "VALUES (datetime('now', '-400 days'), 'x', 'old', 'old')"
                )
            database.init_db()
            with sqlite3.connect(self.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM usage WHERE tool_id = 'old'").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
