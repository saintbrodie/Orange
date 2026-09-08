import os
import sqlite3

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "usage_logs.db")


def _connect(path: str = None):
    database_path = os.path.abspath(path or DB_PATH)
    conn = sqlite3.connect(database_path, timeout=5.0)
    conn.execute("PRAGMA busy_timeout = 5000")
    if database_path == os.path.abspath(DB_PATH):
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _usage_retention_days() -> int:
    try:
        return max(0, int(os.environ.get("ORANGE_USAGE_RETENTION_DAYS", "0")))
    except (TypeError, ValueError):
        return 0


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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_status_timestamp ON usage(status, timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_tool_timestamp ON usage(tool_id, timestamp)")

        retention_days = _usage_retention_days()
        if retention_days > 0:
            conn.execute(
                "DELETE FROM usage WHERE timestamp < datetime('now', ?)",
                (f"-{retention_days} days",),
            )


def _run_with_schema_retry(action, label: str):
    try:
        return action()
    except sqlite3.OperationalError:
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
    error: str = None,
):
    technical_error = error[:8000] if isinstance(error, str) else error

    def action():
        with _connect() as conn:
            conn.execute(
                "INSERT INTO usage (client_ip, tool_id, prompt, prompt_id, backend_url, status, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (client_ip, tool_id, prompt, prompt_id, backend_url, status, technical_error),
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


def validate_database(path: str) -> None:
    with sqlite3.connect(path, timeout=5.0) as conn:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        if not quick_check or quick_check[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(usage)").fetchall()}
        required_columns = {"id", "timestamp", "client_ip", "tool_id", "prompt"}
        missing = required_columns - columns
        if missing:
            raise ValueError(f"Invalid database schema. Missing columns: {sorted(missing)}")


def backup_database(destination_path: str) -> str:
    """Create a transactionally consistent, self-contained SQLite backup."""
    destination_path = os.path.abspath(destination_path)
    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    if os.path.exists(destination_path):
        os.remove(destination_path)

    with _connect() as source, sqlite3.connect(destination_path, timeout=5.0) as destination:
        source.backup(destination)
        destination.commit()
        # A downloaded backup should be a single portable file rather than relying
        # on a matching -wal sidecar.
        destination.execute("PRAGMA journal_mode = DELETE")
        destination.commit()
    return destination_path


def restore_database(source_path: str, backup_path: str = None) -> None:
    """Restore through SQLite's backup API instead of replacing a live DB file."""
    validate_database(source_path)

    if backup_path and os.path.exists(DB_PATH):
        backup_database(backup_path)

    with sqlite3.connect(source_path, timeout=5.0) as source, _connect() as destination:
        source.backup(destination)
        destination.commit()
        try:
            destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass

    # Older valid Orange databases are migrated immediately after restoration.
    init_db()


def get_db_path() -> str:
    return DB_PATH
