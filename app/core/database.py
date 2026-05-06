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

def log_usage(client_ip: str, tool_id: str, prompt: str = None, prompt_id: str = None):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if prompt_id is not None:
                conn.execute("INSERT INTO usage (client_ip, tool_id, prompt, prompt_id) VALUES (?, ?, ?, ?)", (client_ip, tool_id, prompt, prompt_id))
            else:
                # Fallback for old schema if somehow not updated
                conn.execute("INSERT INTO usage (client_ip, tool_id, prompt) VALUES (?, ?, ?)", (client_ip, tool_id, prompt))
    except Exception as e:
        print(f"Error logging usage: {e}")

def get_db_path() -> str:
    return DB_PATH
