from fastapi import APIRouter, Depends

from app.api.admin import verify_admin
from app.core.managed_runtime import managed_runtime_status

router = APIRouter()


@router.get("/api/admin/system/comfyui")
def get_managed_comfyui_status(_=Depends(verify_admin)):
    return managed_runtime_status()
