import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone

import httpx

from app.core.backends import backend_manager, workflow_compatibility_key
from app.core.config import PROJECT_ROOT, get_base_workflow, load_config
from app.core.preflight import run_preflight

RUNTIME_MANIFEST_PATH = os.path.join(PROJECT_ROOT, "runtime", "managed-runtime.json")
ROUTING_BLOCKING_WARNING_CODES = {"value_unavailable"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_managed_runtime_manifest() -> dict:
    try:
        with open(RUNTIME_MANIFEST_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _state_path() -> str | None:
    value = os.environ.get("ORANGE_COMFYUI_STATE", "").strip()
    return os.path.abspath(value) if value else None


def _comfyui_dir() -> str | None:
    value = os.environ.get("ORANGE_COMFYUI_DIR", "").strip()
    if not value:
        return None
    path = os.path.abspath(value)
    return path if os.path.isdir(path) else None


def _read_state() -> dict:
    path = _state_path()
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    path = _state_path()
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _git_head(repo_dir: str | None) -> str | None:
    if not repo_dir:
        return None
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def managed_runtime_status() -> dict:
    manifest = load_managed_runtime_manifest()
    comfy_manifest = manifest.get("comfyui") if isinstance(manifest.get("comfyui"), dict) else {}
    comfy_dir = _comfyui_dir()
    managed = bool(comfy_dir)
    state = _read_state() if managed else {}
    current = _git_head(comfy_dir) if managed else None
    tested = comfy_manifest.get("testedCommit")

    if current and tested and current == tested:
        channel = "tested"
    elif state.get("channel") == "latest":
        channel = "latest"
    elif managed:
        channel = "custom"
    else:
        channel = "external"

    return {
        "managed": managed,
        "currentCommit": current,
        "testedCommit": tested,
        "testedDate": comfy_manifest.get("testedDate"),
        "repository": comfy_manifest.get("repository"),
        "matchesTested": bool(current and tested and current == tested),
        "channel": channel,
        "previousCommit": state.get("previousCommit"),
        "validation": state.get("validation"),
        "validatedAt": state.get("validatedAt"),
        "validationError": state.get("validationError"),
        "tools": state.get("tools") if isinstance(state.get("tools"), list) else [],
    }


def _routing_compatible(backend: dict) -> bool:
    if not backend.get("reachable") or backend.get("errors"):
        return False
    return not any(
        isinstance(warning, dict) and warning.get("code") in ROUTING_BLOCKING_WARNING_CODES
        for warning in (backend.get("warnings") or [])
    )


def _cache_backend_result(backend: dict) -> dict:
    cached = dict(backend)
    if backend.get("reachable") and not _routing_compatible(backend) and not backend.get("errors"):
        errors = list(cached.get("errors") or [])
        errors.append(
            {
                "code": "routing_incompatible",
                "message": "Backend cannot run this workflow with its current model/input inventory.",
            }
        )
        cached["errors"] = errors
    return cached


async def _wait_for_managed_comfyui(url: str, timeout_seconds: int = 90) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    async with httpx.AsyncClient(timeout=3.0) as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                response = await client.get(f"{url.rstrip('/')}/system_stats")
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(1)
    return False


async def validate_pending_managed_runtime() -> None:
    """Validate installed Orange tools after Pinokio changes managed ComfyUI.

    Pinokio marks the runtime state as ``validation: pending`` before the next
    launch. Orange waits for the managed backend, preflights every configured
    workflow against it, refreshes routing compatibility, then records a compact
    pass/fail summary for Admin and rollback decisions.
    """
    state = _read_state()
    if state.get("validation") != "pending" or not _comfyui_dir():
        return

    url = os.environ.get("ORANGE_MANAGED_COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
    if not await _wait_for_managed_comfyui(url):
        state["validationError"] = "Managed ComfyUI did not become reachable before validation timed out."
        state["validatedAt"] = _now_iso()
        # Leave validation pending so the next launch retries automatically.
        _write_state(state)
        return

    config = load_config()
    tools = config.get("tools") if isinstance(config.get("tools"), list) else []
    results = []

    try:
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            tool_id = str(tool.get("id") or "").strip()
            workflow_file = str(tool.get("workflowFile") or "").strip()
            node_mapping = tool.get("nodeMapping") if isinstance(tool.get("nodeMapping"), dict) else {}
            if not tool_id or not workflow_file:
                continue

            try:
                workflow = get_base_workflow(workflow_file)
                preflight = await run_preflight(
                    workflow_file=workflow_file,
                    workflow=workflow,
                    node_mapping=node_mapping,
                    servers=[{"url": url, "priority": 1}],
                )
                backends = preflight.get("backends") if isinstance(preflight.get("backends"), list) else []
                backend = backends[0] if backends else {"url": url, "reachable": False, "errors": [{"code": "no_result", "message": "No preflight result returned."}]}
                compatible = _routing_compatible(backend)

                compatibility_key = workflow_compatibility_key(workflow_file, workflow, node_mapping)
                backend_manager.record_preflight(compatibility_key, [_cache_backend_result(backend)])

                results.append(
                    {
                        "id": tool_id,
                        "name": tool.get("name") or tool_id,
                        "compatible": compatible,
                        "errors": backend.get("errors") or [],
                        "warnings": backend.get("warnings") or [],
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "id": tool_id,
                        "name": tool.get("name") or tool_id,
                        "compatible": False,
                        "errors": [{"code": "validation_exception", "message": str(exc)}],
                        "warnings": [],
                    }
                )

        state["tools"] = results
        state["validation"] = "passed" if all(item.get("compatible") for item in results) else "failed"
        state["validationError"] = None
        state["validatedAt"] = _now_iso()
        state["currentCommit"] = _git_head(_comfyui_dir())
        _write_state(state)
    except Exception as exc:
        state["validation"] = "failed"
        state["validationError"] = str(exc)
        state["validatedAt"] = _now_iso()
        _write_state(state)
