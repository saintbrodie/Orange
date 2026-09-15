import asyncio
import ipaddress
import os

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import get_base_workflow, load_config, save_config
from app.core.onboarding import detect_install_mode, managed_comfy_dir, managed_models_root, mark_setup_complete, setup_required
from app.core.preflight import run_preflight
from app.core.workflow_packs import (
    add_pack_tool_to_config,
    get_workflow_pack,
    install_workflow_pack,
    list_workflow_packs,
    resolve_models_root,
    summarize_system_stats,
)

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


async def _read_backend_metadata(url: str) -> tuple[dict, dict, dict]:
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            object_response = await client.get(f"{url}/object_info")
            object_response.raise_for_status()
            object_info = object_response.json()
            if not isinstance(object_info, dict):
                raise ValueError("Unexpected ComfyUI /object_info response")

            queue_response = await client.get(f"{url}/queue")
            queue = queue_response.json() if queue_response.status_code == 200 else {}

            stats_response = await client.get(f"{url}/system_stats")
            system_stats = stats_response.json() if stats_response.status_code == 200 else {}
            if not isinstance(system_stats, dict):
                system_stats = {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not connect to ComfyUI: {exc}")
    return object_info, queue if isinstance(queue, dict) else {}, system_stats


async def _preflight_pack(pack_id: str, server: dict) -> tuple[dict, bool]:
    manifest = get_workflow_pack(pack_id)
    workflow_file = manifest["workflowFile"]
    tool = manifest["tool"]
    workflow = get_base_workflow(workflow_file)
    node_mapping = tool.get("nodeMapping") or {}
    preflight = await run_preflight(workflow_file, workflow, node_mapping, [server])
    backends = preflight.get("backends") or []
    routable = any(_routing_compatible(backend) for backend in backends)
    compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
    backend_manager.record_preflight(compatibility_key, _cacheable_preflight_results(backends))
    return preflight, routable


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
    object_info, queue, system_stats = await _read_backend_metadata(url)
    hardware = summarize_system_stats(system_stats)

    return {
        "ok": True,
        "url": url,
        "nodeCount": len(object_info),
        "queueRunning": len(queue.get("queue_running", [])),
        "queuePending": len(queue.get("queue_pending", [])),
        "hardware": hardware,
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
    requested_extra = payload.get("extraPacks") or []
    if not isinstance(requested_extra, list):
        raise HTTPException(status_code=400, detail="extraPacks must be a list")

    known_packs = {pack["id"] for pack in list_workflow_packs()}
    extra_packs = []
    for pack_id in requested_extra:
        pack_id = str(pack_id)
        if pack_id == "z-image-turbo":
            continue
        if pack_id not in known_packs:
            raise HTTPException(status_code=400, detail=f"Unknown workflow pack: {pack_id}")
        if pack_id not in extra_packs:
            extra_packs.append(pack_id)

    _object_info, _queue, system_stats = await _read_backend_metadata(comfy_url)
    hardware = summarize_system_stats(system_stats)

    models_root = None
    if install_starter or extra_packs:
        models_root = resolve_models_root(requested_root)
        if not models_root:
            raise HTTPException(
                status_code=400,
                detail="Orange could not determine this ComfyUI installation's models folder. Choose the models folder or skip automatic model installation.",
            )

    install_results = {}
    if install_starter:
        starter_result = await asyncio.to_thread(
            install_workflow_pack,
            "z-image-turbo",
            models_root,
            system_stats,
            True,
        )
        install_results["z-image-turbo"] = starter_result
        if starter_result.get("failures"):
            raise HTTPException(
                status_code=502,
                detail={"message": "One or more Z-Image starter model downloads failed", "result": starter_result},
            )

    config = dict(load_config())
    starter_tool = next((tool for tool in config.get("tools", []) if tool.get("id") == "z-image"), None)
    if not starter_tool:
        raise HTTPException(status_code=500, detail="Z-Image starter tool is missing from the fresh-install config")

    server = {"url": comfy_url, "priority": 1}
    if models_root:
        server["modelsRoot"] = models_root

    starter_preflight, starter_routable = await _preflight_pack("z-image-turbo", server)
    if not starter_routable:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "ComfyUI is reachable, but the Z-Image starter workflow is not ready on this backend.",
                "preflight": starter_preflight,
            },
        )

    optional_results = []
    for pack_id in extra_packs:
        pack_result = {
            "pack": pack_id,
            "installed": False,
            "routable": False,
            "error": None,
        }
        try:
            install_result = await asyncio.to_thread(
                install_workflow_pack,
                pack_id,
                models_root,
                system_stats,
                True,
            )
            install_results[pack_id] = install_result
            if install_result.get("failures"):
                pack_result["error"] = "One or more model downloads failed."
                pack_result["downloadFailures"] = install_result["failures"]
                optional_results.append(pack_result)
                continue

            preflight, routable = await _preflight_pack(pack_id, server)
            pack_result["preflight"] = preflight.get("summary", {})
            pack_result["routable"] = routable
            if routable:
                config = add_pack_tool_to_config(config, pack_id)
                pack_result["installed"] = True
            else:
                pack_result["error"] = "Models were installed, but this ComfyUI build is missing something the workflow needs."
        except Exception as exc:
            pack_result["error"] = str(exc)
        optional_results.append(pack_result)

    config["adminKey"] = admin_key
    config["comfyServers"] = [server]
    save_config(config)
    mark_setup_complete()
    await backend_manager.refresh_all()

    return {
        "status": "success",
        "comfyUrl": comfy_url,
        "hardware": hardware,
        "starter": install_results.get("z-image-turbo"),
        "optionalPacks": optional_results,
        "preflight": {
            "status": starter_preflight.get("summary", {}).get("status"),
            "routableBackends": 1 if starter_routable else 0,
        },
    }
