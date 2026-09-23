import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.api.preflight import _routing_cache_results, _routing_compatible
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import get_base_workflow, load_config, save_config
from app.core.preflight import run_preflight
from app.core.workflow_install_jobs import (
    cancel_job,
    clear_jobs,
    complete_job,
    create_job,
    fail_job,
    get_job,
    list_jobs,
    mark_running,
    request_cancel,
    retry_job,
    set_download_plan,
    update_file_progress,
    update_job,
)
from app.core.workflow_install_runner import InstallCancelled, install_workflow_pack_job
from app.core.workflow_install_support import disk_space, enrich_download_plan, space_requirement
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
_background_install_tasks: set[asyncio.Task] = set()


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


def _job_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            message = str(detail.get("message") or "Workflow setup failed.")
            backend = (detail.get("preflight") or {}).get("backends", [{}])[0]
            findings = []
            if isinstance(backend, dict):
                findings = list(backend.get("errors") or []) + list(backend.get("warnings") or [])
            extra = " ".join(str(item.get("message")) for item in findings if isinstance(item, dict) and item.get("message"))
            return f"{message} {extra}".strip()
    return str(exc) or exc.__class__.__name__


async def _run_install_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    pack_id = str(job.get("packId") or "")
    server_url = str(job.get("serverUrl") or "").rstrip("/")
    requested_root = str(job.get("modelsRoot") or "").strip() or None

    try:
        mark_running(job_id)
        if (get_job(job_id) or {}).get("cancelRequested"):
            raise InstallCancelled("Workflow setup canceled.")
        manifest = get_workflow_pack(pack_id)
        config = dict(load_config())
        server_index, server = _server_for_url(config, server_url)

        update_job(job_id, stage="inspecting", message="Scanning ComfyUI nodes and model inventory…")
        object_info, system_stats = await _backend_metadata(server_url)
        inspection = inspect_workflow_pack(pack_id, object_info, system_stats)
        hardware = summarize_system_stats(system_stats)
        update_job(job_id, hardware=hardware)

        if inspection.get("missingNodes") or inspection.get("unknownModels"):
            missing = inspection.get("missingNodes") or []
            if missing:
                raise HTTPException(status_code=409, detail=f"Missing required ComfyUI nodes: {', '.join(missing)}")
            raise HTTPException(
                status_code=409,
                detail="ComfyUI did not expose enough model inventory to install this pack safely.",
            )

        models_root = resolve_models_root(requested_root or server.get("modelsRoot"))
        if inspection.get("ready"):
            selected_models = inspection.get("selectedModels") or []
            update_job(
                job_id,
                mode="existing",
                stage="materializing",
                message="Binding existing models into the curated workflow…",
                selectedModels=selected_models,
                modelsRoot=models_root,
            )
            set_download_plan(job_id, selected_models)
            for model in selected_models:
                filename = str(model.get("filename") or "existing model")
                update_file_progress(job_id, filename, state="existing")
            if (get_job(job_id) or {}).get("cancelRequested"):
                raise InstallCancelled("Workflow setup canceled.")
            materialize_workflow_pack(pack_id, selected_models)
            install_result = {
                "selectedModels": selected_models,
                "installed": [],
                "skipped": [str(model.get("filename") or "") for model in selected_models],
                "failures": [],
            }
        else:
            if not models_root:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Orange cannot access this backend's model storage. Enter a local/shared ComfyUI models path "
                        "for this server before downloading curated tool models."
                    ),
                )
            selected_models = selection_for_install(inspection)
            download_plan = await enrich_download_plan(
                plan_selected_models(inspection.get("recommendedDownloads") or [], models_root)
            )
            space = space_requirement(download_plan, models_root)
            if space.get("insufficientDiskSpace"):
                need = int(space.get("requiredBytesWithBuffer") or 0)
                free = int((space.get("diskSpace") or {}).get("freeBytes") or 0)
                raise HTTPException(
                    status_code=507,
                    detail={
                        "message": f"Not enough free space for this install. Orange needs {need} bytes including its safety buffer, but only {free} bytes are free.",
                        "diskSpace": space.get("diskSpace"),
                        "requiredBytes": need,
                    },
                )
            update_job(
                job_id,
                mode="download",
                modelsRoot=models_root,
                selectedModels=selected_models,
                stage="downloading",
                message="Downloading missing model files…",
                downloadFileCount=space.get("downloadFileCount", 0),
                downloadBytesTotal=space.get("downloadBytesTotal", 0),
                downloadBytesKnown=space.get("downloadBytesKnown", 0),
                downloadSizeComplete=space.get("downloadSizeComplete", False),
                diskSpace=space.get("diskSpace"),
            )
            set_download_plan(job_id, download_plan)
            install_result = await asyncio.to_thread(
                install_workflow_pack_job,
                job_id,
                pack_id,
                models_root,
                system_stats,
                selected_models,
            )
            if install_result.get("failures"):
                failure = install_result["failures"][0]
                raise HTTPException(
                    status_code=502,
                    detail=f"Download failed for {failure.get('filename', 'model')}: {failure.get('error', 'unknown error')}",
                )

        if (get_job(job_id) or {}).get("cancelRequested"):
            raise InstallCancelled("Workflow setup canceled.")
        update_job(job_id, stage="preflight", message="Running Workflow Preflight…")
        tool, preflight = await _preflight_and_enable(
            config,
            server_index,
            server,
            pack_id,
            manifest,
            models_root,
        )

        result = {
            "status": "success",
            "mode": "existing" if inspection.get("ready") else "downloaded",
            "pack": pack_id,
            "tool": tool,
            "modelsRoot": models_root,
            "hardware": hardware,
            "selectedModels": install_result.get("selectedModels", []),
            "installedFiles": install_result.get("installed", []),
            "skippedFiles": install_result.get("skipped", []),
            "preflight": preflight.get("summary", {}),
        }
        complete_job(job_id, result, message=f"{tool.get('name') or pack_id} is ready.")
    except InstallCancelled:
        cancel_job(job_id)
    except Exception as exc:
        current = get_job(job_id) or {}
        fail_job(job_id, _job_error_message(exc), stage=current.get("stage") or "failed")


def _schedule_install_job(job_id: str) -> None:
    task = asyncio.create_task(_run_install_job(job_id))
    _background_install_tasks.add(task)
    task.add_done_callback(_background_install_tasks.discard)


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
        inspection["downloadPlan"] = await enrich_download_plan(
            plan_selected_models(inspection.get("recommendedDownloads") or [], models_root)
        )
        inspection.update(space_requirement(inspection["downloadPlan"], models_root))
        packs.append(inspection)

    return {
        "serverUrl": server_url,
        "modelsRoot": models_root,
        "hardware": summarize_system_stats(system_stats),
        "diskSpace": disk_space(models_root),
        "packs": packs,
    }


@router.get("/api/admin/workflow-packs/install-jobs")
def get_install_jobs(serverUrl: str | None = None, limit: int = 50, _=Depends(verify_admin)):
    return {"jobs": list_jobs(serverUrl, limit)}


@router.get("/api/admin/workflow-packs/install-jobs/{job_id}")
def get_install_job(job_id: str, _=Depends(verify_admin)):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Workflow install job not found")
    return job


@router.post("/api/admin/workflow-packs/install-jobs")
async def start_install_job(payload: dict, _=Depends(verify_admin)):
    pack_id = str(payload.get("packId") or "").strip()
    server_url = str(payload.get("serverUrl") or "").strip().rstrip("/")
    models_root = str(payload.get("modelsRoot") or "").strip() or None
    if not pack_id or not server_url:
        raise HTTPException(status_code=400, detail="packId and serverUrl are required")

    try:
        get_workflow_pack(pack_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    _server_for_url(load_config(), server_url)

    job, created = create_job(pack_id, server_url, models_root)
    if created:
        _schedule_install_job(job["id"])
    return {"job": job, "created": created}


@router.post("/api/admin/workflow-packs/install-jobs/{job_id}/retry")
async def retry_install_job(job_id: str, _=Depends(verify_admin)):
    try:
        job, created = retry_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Workflow install job not found")
    if created:
        _schedule_install_job(job["id"])
    return {"job": job, "created": created}


@router.post("/api/admin/workflow-packs/install-jobs/{job_id}/cancel")
def cancel_install_job(job_id: str, _=Depends(verify_admin)):
    try:
        return {"job": request_cancel(job_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Workflow install job not found")


@router.delete("/api/admin/workflow-packs/install-jobs")
def clear_install_job_history(serverUrl: str | None = None, _=Depends(verify_admin)):
    return {"deleted": clear_jobs(serverUrl)}


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
                "downloadPlan": plan_selected_models(inspection.get("recommendedDownloads") or [], server.get("modelsRoot")),
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

    object_info, system_stats = await _backend_metadata(server_url)
    inspection = inspect_workflow_pack(pack_id, object_info, system_stats)
    if inspection.get("missingNodes") or inspection.get("unknownModels"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This ComfyUI build is missing required nodes or did not expose enough model inventory to install this pack safely.",
                "inspection": inspection,
            },
        )

    selected_models = selection_for_install(inspection)
    download_plan = plan_selected_models(inspection.get("recommendedDownloads") or [], models_root)
    install_result = await asyncio.to_thread(
        install_workflow_pack,
        pack_id,
        models_root,
        system_stats,
        True,
        selected_models,
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
