import asyncio
import ipaddress
import os
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.api.workflow_pack_admin import _schedule_install_job as schedule_install_job
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import get_base_workflow, load_config, save_config
from app.core.onboarding import detect_install_mode, managed_comfy_dir, managed_models_root, mark_setup_complete, setup_required
from app.core.managed_prompt_enhancer import MANAGED_MODEL_ID, get_status as get_managed_prompt_status, schedule_install as schedule_managed_prompt_install
from app.core.preflight import run_preflight
from app.core.workflow_install_jobs import create_job
from app.core.workflow_pack_probe import (
    inspect_workflow_pack,
    plan_selected_models,
    selection_for_install,
)
from app.core.workflow_packs import (
    add_pack_tool_to_config,
    get_workflow_pack,
    install_workflow_pack,
    list_workflow_packs,
    materialize_workflow_pack,
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
        async with httpx.AsyncClient(timeout=8.0) as client:
            object_response, queue_response, stats_response = await asyncio.gather(
                client.get(f"{url}/object_info"),
                client.get(f"{url}/queue"),
                client.get(f"{url}/system_stats"),
            )
            object_response.raise_for_status()
            object_info = object_response.json()
            if not isinstance(object_info, dict):
                raise ValueError("Unexpected ComfyUI /object_info response")

            queue = queue_response.json() if queue_response.status_code == 200 else {}
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


def _selected_pack_ids(payload: dict, known_packs: set[str]) -> list[str]:
    requested = payload.get("selectedPacks")
    if requested is None:
        requested = []
        if payload.get("installStarter"):
            requested.append("z-image-turbo")
        extras = payload.get("extraPacks") or []
        if isinstance(extras, list):
            requested.extend(extras)
    if not isinstance(requested, list):
        raise HTTPException(status_code=400, detail="selectedPacks must be a list")

    result = []
    for value in requested:
        pack_id = str(value)
        if pack_id not in known_packs:
            raise HTTPException(status_code=400, detail=f"Unknown workflow pack: {pack_id}")
        if pack_id not in result:
            result.append(pack_id)
    return result


def _inspection_payload(manifest: dict, inspection: dict, models_root: str | None) -> dict:
    item = dict(inspection)
    item["description"] = manifest.get("description")
    item["type"] = manifest.get("type")
    item["recommended"] = bool(manifest.get("recommended"))
    item["downloadPlan"] = plan_selected_models(inspection.get("recommendedDownloads") or [], models_root)
    return item


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
        "managedPromptEnhancer": get_managed_prompt_status(),
    }


@router.post("/api/setup/test-backend")
async def test_setup_backend(payload: dict, request: Request):
    _require_setup_client(request)
    _require_setup_pending()
    url = _normalize_url(payload.get("url"))
    requested_root = str(payload.get("modelsRoot") or "").strip() or None
    models_root = resolve_models_root(requested_root)
    object_info, queue, system_stats = await _read_backend_metadata(url)
    hardware = summarize_system_stats(system_stats)

    compatibility = []
    for manifest in list_workflow_packs():
        inspection = inspect_workflow_pack(str(manifest.get("id")), object_info, system_stats)
        compatibility.append(_inspection_payload(manifest, inspection, models_root))

    return {
        "ok": True,
        "url": url,
        "nodeCount": len(object_info),
        "queueRunning": len(queue.get("queue_running", [])),
        "queuePending": len(queue.get("queue_pending", [])),
        "hardware": hardware,
        "modelsRoot": models_root,
        "packCompatibility": compatibility,
    }


@router.post("/api/setup/complete")
async def complete_setup(payload: dict, request: Request):
    _require_setup_client(request)

    admin_key = str(payload.get("adminKey") or "").strip()
    if not setup_required():
        configured_key = str(load_config().get("adminKey") or "")
        if admin_key and configured_key and secrets.compare_digest(admin_key, configured_key):
            return {
                "status": "already_complete",
                "alreadyComplete": True,
                "redirect": "/admin",
                "managedPromptEnhancer": get_managed_prompt_status(),
            }
        raise HTTPException(
            status_code=409,
            detail="Initial setup is already complete. Open Admin and sign in with the password created during setup.",
        )

    if len(admin_key) < 8:
        raise HTTPException(status_code=400, detail="Admin password must be at least 8 characters")

    comfy_url = _normalize_url(payload.get("comfyUrl") or "http://127.0.0.1:8188")
    requested_root = str(payload.get("modelsRoot") or "").strip() or None
    known_packs = {str(pack["id"]) for pack in list_workflow_packs()}
    selected_packs = _selected_pack_ids(payload, known_packs)
    use_managed_prompt = bool(payload.get("managedPromptEnhancer", False))
    managed_prompt_status = get_managed_prompt_status()
    if use_managed_prompt and not managed_prompt_status.get("supported"):
        raise HTTPException(
            status_code=400,
            detail=f"Managed Local prompt enhancement is not packaged for {managed_prompt_status.get('platform', 'this platform')}.",
        )

    object_info, _queue, system_stats = await _read_backend_metadata(comfy_url)
    hardware = summarize_system_stats(system_stats)
    models_root = resolve_models_root(requested_root)

    server = {"url": comfy_url, "priority": 1}
    if models_root:
        server["modelsRoot"] = models_root

    config = dict(load_config())
    config["tools"] = []
    if use_managed_prompt:
        config["llm"] = {
            "enabled": True,
            "provider": "managed",
            "baseUrl": "",
            "apiKey": "",
            "model": MANAGED_MODEL_ID,
        }
    config["adminKey"] = admin_key
    config["comfyServers"] = [server]
    save_config(config)
    mark_setup_complete()
    await backend_manager.refresh_all()

    pack_results = []
    for pack_id in selected_packs:
        manifest = get_workflow_pack(pack_id)
        inspection = inspect_workflow_pack(pack_id, object_info, system_stats)
        result = {
            "pack": pack_id,
            "name": manifest.get("name"),
            "queued": False,
            "jobId": None,
            "error": None,
            "inspection": _inspection_payload(manifest, inspection, models_root),
        }
        if inspection.get("missingNodes"):
            result["error"] = "This ComfyUI build is missing required workflow nodes."
        elif inspection.get("unknownModels"):
            result["error"] = "ComfyUI did not expose enough model inventory to install this workflow safely."
        elif not inspection.get("ready") and not models_root:
            result["error"] = "Required models are missing and Orange does not have a writable models folder for this backend."
        else:
            try:
                job, created = create_job(pack_id, comfy_url, models_root)
                if created:
                    schedule_install_job(job["id"])
                result["queued"] = True
                result["jobId"] = job["id"]
                result["jobState"] = job.get("state")
            except Exception as exc:
                result["error"] = str(exc)
        pack_results.append(result)

    enhancer_result = None
    if use_managed_prompt:
        try:
            enhancer_result = schedule_managed_prompt_install()
        except Exception as exc:
            enhancer_result = {"state": "failed", "error": str(exc)}

    return {
        "status": "success",
        "comfyUrl": comfy_url,
        "hardware": hardware,
        "selectedPackCount": len(selected_packs),
        "queuedPackCount": sum(1 for item in pack_results if item.get("queued")),
        "packs": pack_results,
        "managedPromptEnhancer": enhancer_result,
    }
