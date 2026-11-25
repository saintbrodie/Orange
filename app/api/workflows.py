from fastapi import APIRouter, Request

from app.core.access import enhancement_allowed, is_open_lan, is_team, tool_allowed
from app.core import access, team, team_tools
from app.core.config import load_config
from app.core.public_config import build_public_config

router = APIRouter()


@router.get("/api/workflows")
def get_workflows(request: Request):
    # Never hand the browser a config-shaped object. The admin configuration can
    # grow secrets/operational fields without accidentally exposing them here.
    config = load_config()
    if is_open_lan():
        config = {**config, "tools": [tool for tool in config.get("tools", []) if tool_allowed(tool)]}
    if is_team():
        user = team.request_user(request)
        tools = config.get("tools", [])
        with access.job_db() as connection:
            connection.execute("BEGIN")
            allowed = team_tools.available_tools(connection, user["id"], {tool.get("id") for tool in tools})
        config = {**config, "tools": [tool for tool in tools if tool.get("id") in allowed]}
    public = build_public_config(config)
    if not enhancement_allowed() or (is_team() and config.get("llm", {}).get("provider") != "managed"):
        public["llmEnabled"] = False
    return public
