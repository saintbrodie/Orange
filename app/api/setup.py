import asyncio
import ipaddress
import os

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import get_base_workflow, load_config, save_config
from app.core.onboarding import detect_install_mode, managed_comfy_dir, managed_models_root, mark_setup_complete, setup_required
from app.core.preflight import run_preflight
from app.core.workflow_packs import install_workflow_pack, list_workflow_packs, resolve_models_root

router = APIRouter()
ROUTING_BLOCKING_WARNING_CODES = {"value_unavailable"}


def _require_setup_pending() -> None:
    if not setup_required():
        raise HTTPException(status_code=409, detail="Initial setup is already complete")


def _setup_client_allowed(host: str | None) -> bool:
    if os.environ.get("ORANGE_ALLOW_REMOTE_SETUP", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _require_setup_client(request: Request) -> None:
    host = request.client.host if request.client else None
    if not _setup_client_allowed(host):
        raise HTTPException(
            status_code=403,
            detail=(
                "First-run setup is restricted to the local machine by default. "
                "Run setup locally, use an SSH tunnel, or set ORANGE_ALLOW_REMOTE_SETUP=1 if you intentionally want remote setup."
            ),
        )


def _normalize_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="ComfyUI URL must start with http:// or https://")
    return url


def _routing_compatible(backend: dict) -> bool:
    if not backend.get("reachable") or backend.get("errors"):
        return False
    return not any(
        isinstance(warning, dict) and warning.get("code") in ROUTING_BLOCKING_WARNING_CODES
        for warning in (backend.get("warnings") or [])
    )


def _cacheable_preflight_results(backends: list[dict]) -> list[dict]:
    cached = []
    for backend in backends:
        item = dict(backend)
        if backend.get("reachable") and not _routing_compatible(backend) and not backend.get("errors"):
            item["errors"] = list(item.get("errors") or []) + [
                {
                    "code": "routing_incompatible",
                    "message": "Backend cannot run this workflow with its current model/input inventory.",
                }
            ]
        cached.append(item)
    return cached


@router.get("/api/setup/status")
def get_setup_status(request: Request):
    _require_setup_client(request)
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
async def test_setup_backend(payload: dict, request: Request):
    _require_setup_client(request)
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
async def complete_setup(payload: dict, request: Request):
    _require_setup_client(request)
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
    starter_tool = next((tool for tool in config.get("tools", []) if tool.get("id") == "z-image"), None)
    if not starter_tool:
        raise HTTPException(status_code=500, detail="Z-Image starter tool is missing from the fresh-install config")

    workflow_file = starter_tool.get("workflowFile", "image_z_image_turbo.json")
    node_mapping = starter_tool.get("nodeMapping") or {}
    workflow = get_base_workflow(workflow_file)
    server = {"url": comfy_url, "priority": 1}
    preflight = await run_preflight(workflow_file, workflow, node_mapping, [server])
    backends = preflight.get("backends") or []
    routable_backends = [backend for backend in backends if _routing_compatible(backend)]
    if not routable_backends:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "ComfyUI is reachable, but the Z-Image starter workflow is not ready on this backend.",
                "preflight": preflight,
            },
        )

    compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
    backend_manager.record_preflight(compatibility_key, _cacheable_preflight_results(backends))

    config["adminKey"] = admin_key
    config["comfyServers"] = [server]
    save_config(config)
    mark_setup_complete()
    await backend_manager.refresh_all()

    return {
        "status": "success",
        "comfyUrl": comfy_url,
        "starter": install_result,
        "preflight": {
            "status": preflight.get("summary", {}).get("status"),
            "routableBackends": len(routable_backends),
        },
    }
