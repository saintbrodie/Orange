import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "workflows", "workflows-config.json")

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config_data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

def get_tool_settings(tool_id: str):
    config = load_config()
    for tool in config.get("tools", []):
        if tool.get("id") == tool_id:
            return tool
    return None

def get_base_workflow(workflow_file: str):
    path = os.path.join(os.path.dirname(__file__), "workflows", workflow_file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Workflow file {workflow_file} not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
