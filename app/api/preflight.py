import os
import httpx

from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import PROJECT_ROOT, get_comfy_servers, get_base_workflow
from app.core.model_bindings import backend_inventory, input_options, model_filename, model_references, normalize_backend, save_binding
from app.core.preflight import run_preflight

router = APIRouter()


@router.post("/api/admin/workflows/model-binding")
async def update_model_binding(payload: dict, _=Depends(verify_admin)):
    url = str(payload.get("backendUrl") or "").strip().rstrip("/")
    server = next((s for s in get_comfy_servers() if normalize_backend(s.get("url", "")) == normalize_backend(url)), None)
    if server is None:
        raise HTTPException(status_code=404, detail="Configured backend was not found")
    url = server["url"].rstrip("/")
    filename = str(payload.get("workflowFile") or "")
    if not filename or os.path.basename(filename) != filename or "\\" in filename or filename == "workflows-config.json":
        raise HTTPException(status_code=400, detail="A workflow filename is required")
    try:
        workflow = get_base_workflow(filename)
        async with httpx.AsyncClient() as client:
            info = await backend_inventory(client, url, refresh=True)
        references = model_references(workflow, info)
        reference = next((r for r in references if r["node_id"] == str(payload.get("nodeId")) and r["field"] == payload.get("field")), None)
        if reference is None:
            raise ValueError("This workflow input is not a model selector exposed by the backend")
        # Catalogs may inspect several explicitly declared precision variants.
        # A binding still only records a location; it never changes the graph's
        # selected model. Validate the filename against this loader's inventory.
        logical_filename = payload.get("filename", reference["filename"])
        if not isinstance(logical_filename, str) or model_filename(logical_filename) != logical_filename:
            raise ValueError("A model filename without folders is required")
        if logical_filename != reference["filename"]:
            reference["filename"] = logical_filename
            reference["options"] = [o for o in input_options(info[reference["class_type"]], reference["field"])
                                    if isinstance(o, str) and model_filename(o) == logical_filename]
        path = payload.get("path")
        if path is not None and not isinstance(path, str):
            raise ValueError("Model path must be a string or null")
        save_binding(url, reference, path)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not refresh the backend model inventory") from exc
    backend_manager.invalidate_compatibility(url)
    return {"saved": True, "backendUrl": normalize_backend(url), "category": reference["category"],
            "filename": reference["filename"], "path": path}

# Some preflight findings are intentionally presented as warnings because the
# backend itself is healthy and the workflow remains valid. They can still make
# that backend unsuitable for this specific workflow, though. Keep that routing
# decision separate from the Admin UI severity so operators get a useful yellow
# diagnostic instead of a misleading server-health error.
ROUTING_BLOCKING_WARNING_CODES = {"value_unavailable"}


def _routing_compatible(backend: dict) -> bool:
    if not backend.get("reachable") or backend.get("errors"):
        return False
    return not any(
        isinstance(warning, dict) and warning.get("code") in ROUTING_BLOCKING_WARNING_CODES
        for warning in (backend.get("warnings") or [])
    )


def _routing_cache_results(backends: list[dict]) -> list[dict]:
    """Adapt preflight results for BackendManager without changing UI severity."""
    cached = []
    for backend in backends:
        item = dict(backend)
        if backend.get("reachable") and not _routing_compatible(backend) and not backend.get("errors"):
            errors = list(item.get("errors") or [])
            errors.append(
                {
                    "code": "routing_incompatible",
                    "message": "Backend cannot run this workflow with its current model/input inventory.",
                }
            )
            item["errors"] = errors
        cached.append(item)
    return cached


@router.post("/api/admin/workflows/preflight")
async def preflight_workflow(payload: dict, _=Depends(verify_admin)):
    workflow_file = os.path.basename(str(payload.get("workflowFile", "")).strip())
    if not workflow_file or not workflow_file.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="A valid workflowFile is required")
    if workflow_file == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Config file cannot be preflighted as a workflow")

    node_mapping = payload.get("nodeMapping") or {}
    if not isinstance(node_mapping, dict):
        raise HTTPException(status_code=400, detail="nodeMapping must be an object")

    candidate_paths = [
        os.path.join(PROJECT_ROOT, "workflows", workflow_file),
        os.path.join(PROJECT_ROOT, "workflows", "defaults", workflow_file),
    ]
    path = next((candidate for candidate in candidate_paths if os.path.isfile(candidate)), None)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Workflow file '{workflow_file}' was not found")

    try:
        import json

        with open(path, "r", encoding="utf-8") as handle:
            workflow = json.load(handle)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not read workflow JSON: {exc}")

    result = await run_preflight(
        workflow_file=workflow_file,
        workflow=workflow,
        node_mapping=node_mapping,
        servers=get_comfy_servers(),
    )

    backends = result.get("backends", [])
    for backend in backends:
        backend["routing_compatible"] = _routing_compatible(backend)

    compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
    backend_manager.record_preflight(compatibility_key, _routing_cache_results(backends))

    summary = result.get("summary")
    if isinstance(summary, dict):
        summary["routable_backends"] = sum(1 for backend in backends if backend.get("routing_compatible"))

    result["routing"] = {
        "compatibility_cached": True,
        "compatibility_key": compatibility_key[:12],
    }
    return result
