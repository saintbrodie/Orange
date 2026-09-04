import json
import os
import shutil
import threading

# This file is in app/core/, so project root is two levels up.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
USER_CONFIG_PATH = os.path.join(PROJECT_ROOT, "workflows", "workflows-config.json")
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "workflows", "defaults", "workflows-config.json")

# In-memory cache: invalidated automatically when the file changes on disk.
_config_cache = None
_config_mtime_ns = None
_config_lock = threading.RLock()


def _get_config_mtime_ns():
    try:
        return os.stat(USER_CONFIG_PATH).st_mtime_ns
    except OSError:
        return None


def invalidate_config_cache():
    global _config_cache, _config_mtime_ns
    with _config_lock:
        _config_cache = None
        _config_mtime_ns = None


def load_config():
    global _config_cache, _config_mtime_ns

    with _config_lock:
        current_mtime = _get_config_mtime_ns()
        if _config_cache is not None and current_mtime == _config_mtime_ns:
            return _config_cache

        try:
            with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, json.JSONDecodeError):
            config = {}

        if not os.path.exists(USER_CONFIG_PATH):
            restore_defaults(overwrite=False)

        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            for key, value in user_config.items():
                config[key] = value
        except (OSError, json.JSONDecodeError):
            pass

        _config_cache = config
        _config_mtime_ns = _get_config_mtime_ns()
        return _config_cache


def restore_defaults(overwrite=False):
    """Copies all files from workflows/defaults to workflows/."""
    defaults_dir = os.path.join(PROJECT_ROOT, "workflows", "defaults")
    workflows_dir = os.path.join(PROJECT_ROOT, "workflows")

    if not os.path.exists(defaults_dir):
        return False

    os.makedirs(workflows_dir, exist_ok=True)

    for filename in os.listdir(defaults_dir):
        src = os.path.join(defaults_dir, filename)
        if os.path.isfile(src) and filename.endswith(".json"):
            dst = os.path.join(workflows_dir, filename)
            if overwrite or not os.path.exists(dst):
                shutil.copy2(src, dst)

    defaults_prompts_dir = os.path.join(defaults_dir, "prompts")
    workflows_prompts_dir = os.path.join(workflows_dir, "prompts")
    if os.path.exists(defaults_prompts_dir):
        os.makedirs(workflows_prompts_dir, exist_ok=True)
        for filename in os.listdir(defaults_prompts_dir):
            if filename.endswith(".txt"):
                src = os.path.join(defaults_prompts_dir, filename)
                dst = os.path.join(workflows_prompts_dir, filename)
                if overwrite or not os.path.exists(dst):
                    shutil.copy2(src, dst)

    # copy2 preserves source mtimes, so explicit invalidation is required.
    invalidate_config_cache()
    return True


def get_system_prompt(tool_id: str = None) -> str:
    """Retrieve a tool-specific system prompt or fall back to the global prompt."""
    if tool_id and tool_id.lower() == "global":
        tool_id = None

    if tool_id:
        active_tool_path = os.path.join(PROJECT_ROOT, "workflows", "prompts", f"{tool_id}.txt")
        if os.path.exists(active_tool_path):
            with open(active_tool_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content

        default_tool_path = os.path.join(PROJECT_ROOT, "workflows", "defaults", "prompts", f"{tool_id}.txt")
        if os.path.exists(default_tool_path):
            with open(default_tool_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content

    active_global_path = os.path.join(PROJECT_ROOT, "workflows", "prompts", "global.txt")
    if os.path.exists(active_global_path):
        with open(active_global_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content

    default_global_path = os.path.join(PROJECT_ROOT, "workflows", "defaults", "prompts", "global.txt")
    if os.path.exists(default_global_path):
        with open(default_global_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content

    return "You are a prompt enhancer for text-to-image models. Expand the user's prompt with rich details, style, lighting, and composition. Keep it under 80 words. Respond with ONLY the enhanced prompt."


def save_config(config_data):
    global _config_cache, _config_mtime_ns

    # Import lazily to keep config loading independent from the heavier workflow
    # validation module during application startup.
    from app.core.config_validation import validate_config

    validation = validate_config(config_data)
    if validation["errors"]:
        details = "; ".join(
            f"{issue['path']}: {issue['message']}" for issue in validation["errors"][:8]
        )
        remaining = len(validation["errors"]) - 8
        if remaining > 0:
            details += f"; plus {remaining} more error(s)"
        raise ValueError(f"Config validation failed: {details}")

    os.makedirs(os.path.dirname(USER_CONFIG_PATH), exist_ok=True)
    tmp_path = USER_CONFIG_PATH + ".tmp"

    with _config_lock:
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, USER_CONFIG_PATH)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        _config_cache = config_data
        _config_mtime_ns = _get_config_mtime_ns()

    for warning in validation["warnings"]:
        print(f"Config warning [{warning['path']}]: {warning['message']}")
    return validation


def get_tool_settings(tool_id: str):
    config = load_config()
    for tool in config.get("tools", []):
        if tool.get("id") == tool_id:
            return tool
    return None


def get_base_workflow(workflow_file: str):
    if not isinstance(workflow_file, str) or not workflow_file.lower().endswith(".json"):
        raise FileNotFoundError("Invalid workflow filename.")
    safe_name = os.path.basename(workflow_file)
    if safe_name != workflow_file:
        raise FileNotFoundError("Workflow files must live directly inside Orange's workflows folder.")

    path = os.path.join(PROJECT_ROOT, "workflows", safe_name)
    if not os.path.exists(path):
        path = os.path.join(PROJECT_ROOT, "workflows", "defaults", safe_name)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Workflow file {safe_name} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_comfy_servers():
    config = load_config()
    servers = config.get("comfyServers", [])
    if not servers:
        legacy_url = config.get("comfyServerUrl", "http://127.0.0.1:8188")
        servers = [{"url": legacy_url, "priority": 1}]

    return sorted(servers, key=lambda x: int(x.get("priority", 1)))
