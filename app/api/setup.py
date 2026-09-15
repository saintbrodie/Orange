import asyncio

import httpx
from fastapi import APIRouter, HTTPException

from app.core.backends import backend_manager
from app.core.config import load_config, save_config
from app.core.onboarding import detect_install_mode, managed_comfy_dir, managed_models_root, mark_setup_complete, setup_required
from app.core.workflow_packs import install_workflow_pack, list_workflow_packs, resolve_models_root

router = APIRouter()


def _require_setup_pending() -> None:
    if not setup_required():
        raise HTTPException(status_code=409, detail="Initial setup is already complete")


def _normalize_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="ComfyUI URL must start with http:// or https://")
    return url


@router.get("/api/setup/status")
def get_setup_status():
    required = setup_required()
    mode = detect_install_mode()
    if not required:
        return {"required": False, "installMode": mode}

    managed_dir = managed_comfy_dir()
    model_root = managed_models_root() or resolve_models_root()
    return {
        "required": True,
        "installMode": mode,
        "managedComfyAvailable": bool(managed_dir),
        "defaultComfyUrl": "http://127.0.0.1:8188",
        "detectedModelsRoot": model_root,
        "packs": list_workflow_packs(),
    }


@router.post("/api/setup/test-backend")
async def test_setup_backend(payload: dict):
    _require_setup_pending()
    url = _normalize_url(payload.get("url"))
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(f"{url}/object_info")
            response.raise_for_status()
            object_info = response.json()
            if not isinstance(object_info, dict):
                raise ValueError("Unexpected ComfyUI response")
            queue_response = await client.get(f"{url}/queue")
            queue = queue_response.json() if queue_response.status_code == 200 else {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not connect to ComfyUI: {exc}")

    return {
        "ok": True,
        "url": url,
        "nodeCount": len(object_info),
        "queueRunning": len(queue.get("queue_running", [])) if isinstance(queue, dict) else 0,
        "queuePending": len(queue.get("queue_pending", [])) if isinstance(queue, dict) else 0,
    }


@router.post("/api/setup/complete")
async def complete_setup(payload: dict):
    _require_setup_pending()

    admin_key = str(payload.get("adminKey") or "").strip()
    if len(admin_key) < 8:
        raise HTTPException(status_code=400, detail="Admin password must be at least 8 characters")

    comfy_url = _normalize_url(payload.get("comfyUrl") or "http://127.0.0.1:8188")
    install_starter = bool(payload.get("installStarter", True))
    requested_root = str(payload.get("modelsRoot") or "").strip() or None

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(f"{comfy_url}/object_info")
            response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ComfyUI must be reachable before setup can finish: {exc}")

    install_result = None
    if install_starter:
        models_root = resolve_models_root(requested_root)
        if not models_root:
            raise HTTPException(
                status_code=400,
                detail="Orange could not determine this ComfyUI installation's models folder. Choose the models folder or skip automatic model installation.",
            )
        install_result = await asyncio.to_thread(install_workflow_pack, "z-image-turbo", models_root)
        if install_result.get("failures"):
            raise HTTPException(status_code=502, detail={"message": "One or more model downloads failed", "result": install_result})

    config = dict(load_config())
    config["adminKey"] = admin_key
    config["comfyServers"] = [{"url": comfy_url, "priority": 1}]
    save_config(config)
    mark_setup_complete()
    await backend_manager.refresh_all()

    return {
        "status": "success",
        "comfyUrl": comfy_url,
        "starter": install_result,
    }
