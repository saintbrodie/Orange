from fastapi import APIRouter, Depends

from app.api.admin import verify_admin
from app.core.backends import backend_manager

router = APIRouter()


@router.get("/api/admin/backends/status")
async def get_backend_status(refresh: bool = False, _=Depends(verify_admin)):
    if refresh:
        await backend_manager.refresh_all()

    return {
        "backends": backend_manager.snapshot(),
        "settings": {
            "poll_interval_seconds": backend_manager.poll_interval,
            "probe_timeout_seconds": backend_manager.probe_timeout,
            "failure_threshold": backend_manager.failure_threshold,
            "backoff_seconds": backend_manager.backoff_seconds,
        },
    }
