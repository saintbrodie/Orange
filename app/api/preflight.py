import os

from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import PROJECT_ROOT, get_comfy_servers
from app.core.preflight import run_preflight

router = APIRouter()


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

    compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
    backend_manager.record_preflight(compatibility_key, result.get("backends", []))
    result["routing"] = {
        "compatibility_cached": True,
        "compatibility_key": compatibility_key[:12],
    }
    return result
