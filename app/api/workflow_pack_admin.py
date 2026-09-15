import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.api.preflight import _routing_cache_results, _routing_compatible
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import get_base_workflow, load_config, save_config
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


def _server_for_url(config: dict, url: str) -> tuple[int, dict]:
    normalized = str(url or "").strip().rstrip("/")
    for index, server in enumerate(config.get("comfyServers") or []):
        if str(server.get("url") or "").strip().rstrip("/") == normalized:
            return index, dict(server)
    raise HTTPException(status_code=404, detail="Configured ComfyUI server was not found")


async def _system_stats(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(f"{url.rstrip('/')}/system_stats")
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not read ComfyUI system information: {exc}")


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
                "for this server before installing curated tools."
            ),
        )

    system_stats = await _system_stats(server_url)
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
            detail={"message": "One or more model downloads failed", "result": install_result},
        )

    workflow_file = manifest["workflowFile"]
    tool = manifest["tool"]
    workflow = get_base_workflow(workflow_file)
    node_mapping = tool.get("nodeMapping") or {}
    preflight_server = {
        "url": server_url,
        "priority": server.get("priority", 1),
        "modelsRoot": models_root,
    }
    preflight = await run_preflight(workflow_file, workflow, node_mapping, [preflight_server])
    backends = preflight.get("backends") or []
    routable = any(_routing_compatible(backend) for backend in backends)

    compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
    backend_manager.record_preflight(compatibility_key, _routing_cache_results(backends))

    if not routable:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Models were installed, but this backend is not ready to run the curated workflow.",
                "preflight": preflight,
                "install": install_result,
            },
        )

    config = add_pack_tool_to_config(config, pack_id)
    servers = [dict(item) if isinstance(item, dict) else item for item in (config.get("comfyServers") or [])]
    if isinstance(servers[server_index], dict):
        servers[server_index]["modelsRoot"] = models_root
    config["comfyServers"] = servers
    save_config(config)
    await backend_manager.refresh_all()

    return {
        "status": "success",
        "pack": pack_id,
        "tool": tool,
        "modelsRoot": models_root,
        "hardware": summarize_system_stats(system_stats),
        "selectedModels": install_result.get("selectedModels", []),
        "installedFiles": install_result.get("installed", []),
        "skippedFiles": install_result.get("skipped", []),
        "preflight": preflight.get("summary", {}),
    }
