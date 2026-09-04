import os
import sqlite3

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "usage_logs.db")


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                tool_id TEXT,
                prompt TEXT,
                prompt_id TEXT,
                backend_url TEXT,
                status TEXT DEFAULT 'queued',
                error TEXT
            )
            """
        )

        migrations = [
            ("prompt_id", "TEXT"),
            ("backend_url", "TEXT"),
            ("status", "TEXT DEFAULT 'queued'"),
            ("error", "TEXT"),
        ]
        for column, definition in migrations:
            try:
                conn.execute(f"ALTER TABLE usage ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass

        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_prompt_id ON usage(prompt_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage(timestamp)")


def _run_with_schema_retry(action, label: str):
    try:
        return action()
    except sqlite3.OperationalError as exc:
        # An older database can be restored while Orange is running. Re-apply the
        # additive schema migrations and retry once instead of requiring a restart.
        try:
            init_db()
            return action()
        except Exception as retry_exc:
            print(f"Error {label} after schema repair: {retry_exc}")
            return None
    except Exception as exc:
        print(f"Error {label}: {exc}")
        return None


def log_usage(
    client_ip: str,
    tool_id: str,
    prompt: str = None,
    prompt_id: str = None,
    backend_url: str = None,
    status: str = "queued",
):
    def action():
        with _connect() as conn:
            conn.execute(
                "INSERT INTO usage (client_ip, tool_id, prompt, prompt_id, backend_url, status) VALUES (?, ?, ?, ?, ?, ?)",
                (client_ip, tool_id, prompt, prompt_id, backend_url, status),
            )

    _run_with_schema_retry(action, "logging usage")


def update_usage_status(prompt_id: str, status: str, error: str = None):
    if not prompt_id:
        return
    technical_error = error[:8000] if isinstance(error, str) else error

    def action():
        with _connect() as conn:
            conn.execute(
                "UPDATE usage SET status = ?, error = ? WHERE prompt_id = ?",
                (status, technical_error, prompt_id),
            )

    _run_with_schema_retry(action, "updating usage status")


def get_backend_for_prompt(prompt_id: str) -> str:
    def action():
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT backend_url FROM usage WHERE prompt_id = ?", (prompt_id,))
            row = cursor.fetchone()
            if row and row["backend_url"]:
                return row["backend_url"]
        return None

    return _run_with_schema_retry(action, "fetching backend")


def get_generation_record(prompt_id: str):
    def action():
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usage WHERE prompt_id = ? ORDER BY id DESC LIMIT 1", (prompt_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    return _run_with_schema_retry(action, "fetching generation record")


def delete_usage(prompt_id: str):
    def action():
        with _connect() as conn:
            conn.execute("DELETE FROM usage WHERE prompt_id = ?", (prompt_id,))

    _run_with_schema_retry(action, "deleting usage")


def get_db_path() -> str:
    return DB_PATH
