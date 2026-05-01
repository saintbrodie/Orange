import json
import os

# We assume the working directory is still the project root (f:\Orange)
# So 'workflows' directory is in the parent of the 'app' directory, or we can just use the CWD.
# Let's dynamically find the project root from this file's location.
# This file is in app/core/, so project root is two levels up.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "workflows", "workflows-config.json")

# In-memory cache: invalidated automatically when the file changes on disk
_config_cache = None
_config_mtime = 0.0

def load_config():
    global _config_cache, _config_mtime
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        mtime = 0.0
    if _config_cache is None or mtime > _config_mtime:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = json.load(f)
        _config_mtime = mtime
    return _config_cache

def save_config(config_data):
    global _config_cache, _config_mtime
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    # Update cache immediately so subsequent reads don't hit disk
    _config_cache = config_data
    _config_mtime = os.path.getmtime(CONFIG_PATH)

def get_tool_settings(tool_id: str):
    config = load_config()
    for tool in config.get("tools", []):
        if tool.get("id") == tool_id:
            return tool
    return None

def get_base_workflow(workflow_file: str):
    path = os.path.join(PROJECT_ROOT, "workflows", workflow_file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Workflow file {workflow_file} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
