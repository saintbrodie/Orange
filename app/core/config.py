import json
import os
import shutil

# We assume the working directory is still the project root (f:\Orange)
# So 'workflows' directory is in the parent of the 'app' directory, or we can just use the CWD.
# Let's dynamically find the project root from this file's location.
# This file is in app/core/, so project root is two levels up.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
USER_CONFIG_PATH = os.path.join(PROJECT_ROOT, "workflows", "workflows-config.json")
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "workflows", "defaults", "workflows-config.json")

# In-memory cache: invalidated automatically when the file changes on disk
_config_cache = None
_config_mtime = 0.0

def load_config():
    global _config_cache, _config_mtime
    try:
        mtime = os.path.getmtime(USER_CONFIG_PATH)
    except OSError:
        mtime = 0.0
        
    if _config_cache is None or mtime > _config_mtime:
        # 1. Load default config
        try:
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        except OSError:
            config = {}
            
        # 2. Check if user config exists. If not, initialize from defaults.
        if not os.path.exists(USER_CONFIG_PATH):
            restore_defaults(overwrite=False)

        # 3. Load user config and merge
        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
                
            # Merge user_config into config
            for key, value in user_config.items():
                config[key] = value # Replaces tools entirely if user modified it
                
        except OSError:
            pass

        _config_cache = config
        _config_mtime = mtime
    return _config_cache

def restore_defaults(overwrite=False):
    """Copies all files from workflows/defaults to workflows/"""
    defaults_dir = os.path.join(PROJECT_ROOT, "workflows", "defaults")
    workflows_dir = os.path.join(PROJECT_ROOT, "workflows")
    
    if not os.path.exists(defaults_dir):
        return False
        
    for filename in os.listdir(defaults_dir):
        if filename.endswith(".json"):
            src = os.path.join(defaults_dir, filename)
            dst = os.path.join(workflows_dir, filename)
            if overwrite or not os.path.exists(dst):
                shutil.copy2(src, dst)
    return True

def save_config(config_data):
    global _config_cache, _config_mtime
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    # Update cache immediately so subsequent reads don't hit disk
    _config_cache = config_data
    _config_mtime = os.path.getmtime(USER_CONFIG_PATH)

def get_tool_settings(tool_id: str):
    config = load_config()
    for tool in config.get("tools", []):
        if tool.get("id") == tool_id:
            return tool
    return None

def get_base_workflow(workflow_file: str):
    path = os.path.join(PROJECT_ROOT, "workflows", workflow_file)
    if not os.path.exists(path):
        # Fallback to defaults
        path = os.path.join(PROJECT_ROOT, "workflows", "defaults", workflow_file)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Workflow file {workflow_file} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_comfy_servers():
    config = load_config()
    servers = config.get("comfyServers", [])
    if not servers:
        # Fallback to single URL
        legacy_url = config.get("comfyServerUrl", "http://127.0.0.1:8188")
        servers = [{"url": legacy_url, "priority": 1}]
    
    # Sort servers by priority (lowest number first)
    return sorted(servers, key=lambda x: int(x.get("priority", 1)))
