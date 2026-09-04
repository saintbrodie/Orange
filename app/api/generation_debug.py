from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.core.database import get_generation_record

router = APIRouter()


@router.get("/api/admin/generations/{prompt_id}")
def get_generation_debug(prompt_id: str, _=Depends(verify_admin)):
    record = get_generation_record(prompt_id)
    if not record:
        raise HTTPException(status_code=404, detail="Generation not found")

    return {
        "prompt_id": record.get("prompt_id"),
        "tool_id": record.get("tool_id"),
        "backend_url": record.get("backend_url"),
        "timestamp": record.get("timestamp"),
        "status": record.get("status") or "unknown",
        "error": record.get("error"),
    }
