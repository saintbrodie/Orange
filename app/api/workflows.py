from fastapi import APIRouter
from app.core.config import load_config

router = APIRouter()

@router.get("/api/workflows")
def get_workflows():
    current_config = load_config()
    result = {
        "tools": current_config.get("tools", []),
        "aspectRatios": current_config.get("aspectRatios", {})
    }
    if current_config.get("modifyTool"):
        result["modifyTool"] = current_config["modifyTool"]
    return result
