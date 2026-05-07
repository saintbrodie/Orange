import sqlite3
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "usage_logs.db")

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                client_ip TEXT,
                tool_id TEXT,
                prompt TEXT
            )
        ''')
        try:
            conn.execute('ALTER TABLE usage ADD COLUMN prompt_id TEXT')
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute('ALTER TABLE usage ADD COLUMN backend_url TEXT')
        except sqlite3.OperationalError:
            pass

def log_usage(client_ip: str, tool_id: str, prompt: str = None, prompt_id: str = None, backend_url: str = None):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO usage (client_ip, tool_id, prompt, prompt_id, backend_url) VALUES (?, ?, ?, ?, ?)",
                (client_ip, tool_id, prompt, prompt_id, backend_url)
            )
    except Exception as e:
        print(f"Error logging usage: {e}")

def get_backend_for_prompt(prompt_id: str) -> str:
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT backend_url FROM usage WHERE prompt_id = ?", (prompt_id,))
            row = c.fetchone()
            if row and row["backend_url"]:
                return row["backend_url"]
    except Exception as e:
        print(f"Error fetching backend: {e}")
    return None

def delete_usage(prompt_id: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM usage WHERE prompt_id = ?", (prompt_id,))
    except Exception as e:
        print(f"Error deleting usage: {e}")

def get_db_path() -> str:
    return DB_PATH
