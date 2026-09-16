import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.api.preflight import _routing_cache_results, _routing_compatible
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import get_base_workflow, load_config, save_config
from app.core.preflight import run_preflight
from app.core.workflow_pack_probe import inspect_workflow_pack, plan_workflow_pack
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


def _server_for_url(config: dict, url: str) -> tuple[int, dict]:
    normalized = str(url or "").strip().rstrip("/")
    for index, server in enumerate(config.get("comfyServers") or []):
        if str(server.get("url") or "").strip().rstrip("/") == normalized:
            return index, dict(server)
    raise HTTPException(status_code=404, detail="Configured ComfyUI server was not found")


async def _backend_metadata(url: str) -> tuple[dict, dict]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            object_response, stats_response = await asyncio.gather(
                client.get(f"{url.rstrip('/')}/object_info"),
                client.get(f"{url.rstrip('/')}/system_stats"),
            )
            object_response.raise_for_status()
            stats_response.raise_for_status()
            object_info = object_response.json()
            system_stats = stats_response.json()
            if not isinstance(object_info, dict):
                raise ValueError("ComfyUI returned invalid /object_info data")
            if not isinstance(system_stats, dict):
                system_stats = {}
            return object_info, system_stats
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not inspect ComfyUI: {exc}")


async def _system_stats(url: str) -> dict:
    _object_info, system_stats = await _backend_metadata(url)
    return system_stats


async def _preflight_and_enable(
    config: dict,
    server_index: int,
    server: dict,
    pack_id: str,
    manifest: dict,
    models_root: str | None = None,
) -> tuple[dict, dict]:
    workflow_file = manifest["workflowFile"]
    tool = manifest["tool"]
    workflow = get_base_workflow(workflow_file)
    node_mapping = tool.get("nodeMapping") or {}
    preflight_server = {
        "url": server["url"],
        "priority": server.get("priority", 1),
    }
    if models_root:
        preflight_server["modelsRoot"] = models_root

    preflight = await run_preflight(workflow_file, workflow, node_mapping, [preflight_server])
    backends = preflight.get("backends") or []
    routable = any(_routing_compatible(backend) for backend in backends)

    compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
    backend_manager.record_preflight(compatibility_key, _routing_cache_results(backends))

    if not routable:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This backend is not ready to run the curated workflow.",
                "preflight": preflight,
            },
        )

    updated = add_pack_tool_to_config(config, pack_id)
    servers = [dict(item) if isinstance(item, dict) else item for item in (updated.get("comfyServers") or [])]
    if models_root and isinstance(servers[server_index], dict):
        servers[server_index]["modelsRoot"] = models_root
    updated["comfyServers"] = servers
    save_config(updated)
    await backend_manager.refresh_all()
    return tool, preflight


@router.get("/api/admin/workflow-packs")
def get_workflow_pack_catalog(_=Depends(verify_admin)):
    config = load_config()
    installed_tool_ids = {
        str(tool.get("id"))
        for tool in (config.get("tools") or [])
        if isinstance(tool, dict) and tool.get("id")
    }
    packs = []
    for manifest in list_workflow_packs():
        item = dict(manifest)
        tool = manifest.get("tool") if isinstance(manifest.get("tool"), dict) else {}
        item["installed"] = bool(tool.get("id") in installed_tool_ids)
        packs.append(item)

    servers = []
    for server in config.get("comfyServers") or []:
        if not isinstance(server, dict) or not server.get("url"):
            continue
        servers.append(
            {
                "url": server.get("url"),
                "priority": server.get("priority", 1),
                "modelsRoot": server.get("modelsRoot"),
            }
        )

    return {
        "packs": packs,
        "servers": servers,
        "detectedModelsRoot": resolve_models_root(),
    }


@router.post("/api/admin/workflow-packs/inspect")
async def inspect_admin_workflow_packs(payload: dict, _=Depends(verify_admin)):
    server_url = str(payload.get("serverUrl") or "").strip().rstrip("/")
    requested_root = str(payload.get("modelsRoot") or "").strip() or None
    if not server_url:
        raise HTTPException(status_code=400, detail="serverUrl is required")

    config = dict(load_config())
    _server_index, server = _server_for_url(config, server_url)
    models_root = resolve_models_root(requested_root or server.get("modelsRoot"))
    object_info, system_stats = await _backend_metadata(server_url)
    installed_tool_ids = {
        str(tool.get("id"))
        for tool in (config.get("tools") or [])
        if isinstance(tool, dict) and tool.get("id")
    }

    packs = []
    for manifest in list_workflow_packs():
        pack_id = str(manifest.get("id"))
        inspection = inspect_workflow_pack(pack_id, object_info, system_stats)
        inspection["installed"] = bool((manifest.get("tool") or {}).get("id") in installed_tool_ids)
        inspection["downloadPlan"] = plan_workflow_pack(pack_id, system_stats, models_root)
        packs.append(inspection)

    return {
        "serverUrl": server_url,
        "modelsRoot": models_root,
        "hardware": summarize_system_stats(system_stats),
        "packs": packs,
    }


@router.post("/api/admin/workflow-packs/activate")
async def activate_admin_workflow_pack(payload: dict, _=Depends(verify_admin)):
    pack_id = str(payload.get("packId") or "").strip()
    server_url = str(payload.get("serverUrl") or "").strip().rstrip("/")
    if not pack_id or not server_url:
        raise HTTPException(status_code=400, detail="packId and serverUrl are required")

    try:
        manifest = get_workflow_pack(pack_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    config = dict(load_config())
    server_index, server = _server_for_url(config, server_url)
    object_info, system_stats = await _backend_metadata(server_url)
    inspection = inspect_workflow_pack(pack_id, object_info, system_stats)
    if not inspection.get("ready"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The connected ComfyUI does not already have everything this workflow needs.",
                "inspection": inspection,
                "downloadPlan": plan_workflow_pack(pack_id, system_stats, server.get("modelsRoot")),
            },
        )

    materialize_workflow_pack(pack_id, inspection.get("selectedModels") or [])
    tool, preflight = await _preflight_and_enable(
        config,
        server_index,
        server,
        pack_id,
        manifest,
        server.get("modelsRoot"),
    )
    return {
        "status": "success",
        "mode": "existing",
        "pack": pack_id,
        "tool": tool,
        "selectedModels": inspection.get("selectedModels") or [],
        "preflight": preflight.get("summary", {}),
    }


@router.post("/api/admin/workflow-packs/install")
async def install_admin_workflow_pack(payload: dict, _=Depends(verify_admin)):
    pack_id = str(payload.get("packId") or "").strip()
    server_url = str(payload.get("serverUrl") or "").strip().rstrip("/")
    requested_root = str(payload.get("modelsRoot") or "").strip() or None
    if not pack_id or not server_url:
        raise HTTPException(status_code=400, detail="packId and serverUrl are required")

    try:
        manifest = get_workflow_pack(pack_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    config = dict(load_config())
    server_index, server = _server_for_url(config, server_url)
    models_root = resolve_models_root(requested_root or server.get("modelsRoot"))
    if not models_root:
        raise HTTPException(
            status_code=400,
            detail=(
                "Orange cannot access this backend's model storage. Enter a local/shared ComfyUI models path "
                "for this server before downloading curated tool models."
            ),
        )

    system_stats = await _system_stats(server_url)
    download_plan = plan_workflow_pack(pack_id, system_stats, models_root)
    install_result = await asyncio.to_thread(
        install_workflow_pack,
        pack_id,
        models_root,
        system_stats,
        True,
    )
    if install_result.get("failures"):
        raise HTTPException(
            status_code=502,
            detail={"message": "One or more model downloads failed", "result": install_result, "downloadPlan": download_plan},
        )

    tool, preflight = await _preflight_and_enable(
        config,
        server_index,
        server,
        pack_id,
        manifest,
        models_root,
    )

    return {
        "status": "success",
        "mode": "downloaded",
        "pack": pack_id,
        "tool": tool,
        "modelsRoot": models_root,
        "hardware": summarize_system_stats(system_stats),
        "downloadPlan": download_plan,
        "selectedModels": install_result.get("selectedModels", []),
        "installedFiles": install_result.get("installed", []),
        "skippedFiles": install_result.get("skipped", []),
        "preflight": preflight.get("summary", {}),
    }
