import os

from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import PROJECT_ROOT, get_comfy_servers
from app.core.preflight import run_preflight

router = APIRouter()

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
