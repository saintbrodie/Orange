import asyncio
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
from collections import Counter
from contextlib import closing
from dataclasses import asdict

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import PROJECT_ROOT, get_comfy_servers, get_system_prompt, load_config, restore_defaults, save_config
from app.core.database import delete_usage, get_backend_for_prompt, get_db_path
from app.core.outputs import collect_media_outputs
from app.core import huggingface
from app.core import access, listener, team

router = APIRouter()

MAX_WORKFLOW_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DB_RESTORE_BYTES = 250 * 1024 * 1024


async def verify_admin(authorization: str = Header(None), request: Request = None):
    if access.is_team():
        return team.request_user(request, "owner")
    config = load_config()
    expected_key = config.get("adminKey", "orangeadmin")
    if access.is_open_lan() and expected_key == "orangeadmin" and request is not None:
        peer = request.client.host if request.client else None
        if peer not in {"127.0.0.1", "::1"} and not access.allows_direct_lan_http(request):
            raise HTTPException(403, "Use localhost with the factory Admin Key, or enable LAN HTTP on the Orange host for direct private-LAN access.")
    if not authorization or not secrets.compare_digest(authorization.encode(), f"Bearer {expected_key}".encode()):
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid admin key")
    return True


async def verify_analytics(authorization: str = Header(None), request: Request = None):
    if access.is_team():
        return team.request_user(request, "owner", "operator")
    return await verify_admin(authorization, request)


async def _read_limited_upload(file: UploadFile, limit_bytes: int, label: str) -> bytes:
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit_bytes:
            raise HTTPException(status_code=413, detail=f"{label} exceeds the upload limit")
    return bytes(data)


def _html_safe_log(row: dict | None) -> dict | None:
    """Escape values that the legacy admin UI interpolates into innerHTML."""
    if not row:
        return row
    safe = dict(row)
    for key in ("prompt", "client_ip", "tool_id", "backend_url", "provider", "model", "status"):
        value = safe.get(key)
        if isinstance(value, str):
            safe[key] = html.escape(value, quote=True)
    return safe


PERIOD_FILTERS = {
    "all": "",
    "today": "WHERE date(timestamp) = date('now')",
    "weekly": "WHERE timestamp >= datetime('now', '-7 days')",
    "monthly": "WHERE timestamp >= datetime('now', '-1 month')",
    "quarterly": "WHERE timestamp >= datetime('now', '-3 months')",
    "yearly": "WHERE timestamp >= datetime('now', '-1 year')",
}


@router.get("/api/admin/system/check-updates")
def check_updates(_=Depends(verify_admin)):
    try:
        subprocess.run(["git", "fetch"], check=True, capture_output=True, cwd=PROJECT_ROOT)
        local = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT).decode().strip()
        remote = subprocess.check_output(["git", "rev-parse", "@{u}"], cwd=PROJECT_ROOT).decode().strip()
        return {
            "update_available": local != remote,
            "current_version": local[:7],
            "remote_version": remote[:7],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to check updates: {exc}")


@router.post("/api/admin/system/update")
def apply_update(_=Depends(verify_admin)):
    try:
        subprocess.run(["git", "pull", "--ff-only"], check=True, capture_output=True, cwd=PROJECT_ROOT)
        return {"status": "success", "message": "Updated to latest version. Please restart the server."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update: {exc}")


@router.post("/api/admin/system/restart")
def restart_server(request: Request, _=Depends(verify_admin)):
    if not os.environ.get("ORANGE_RUNNING_PORT"):
        raise HTTPException(409, "Restart Orange with its launcher or your service manager.")
    try:
        settings = listener.configured_settings()
        _validate_listener_change(settings, _active_listener(request))
        if listener.needs_launcher_relaunch(settings):
            raise HTTPException(409, "Stop and relaunch Orange to apply Team mode with LAN HTTP. The running launcher predates Team LAN access.")
        listener.RESTART_PATH.touch()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(500, "Orange could not request a restart. Check the launcher settings and logs.") from exc
    return {"status": "restarting", "pending": asdict(settings)}


def _active_listener(request):
    server = request.scope.get("server") or (None, 7070)
    mode = access.access_mode()
    return listener.ListenerSettings(mode, int(os.environ.get("ORANGE_RUNNING_PORT") or server[1] or 7070),
                                     mode != "local" and listener.lan_http_requested())


def _validate_listener_change(settings, active, *, creating_owner=False):
    if settings.mode == "team" and active.mode != "team" and not creating_owner and not team.has_active_owner():
        raise HTTPException(409, "Create a Team owner in System Management before switching to Team mode.")
    if settings.port != active.port:
        try:
            listener.check_port(settings)
        except OSError as exc:
            raise HTTPException(409, f"Port {settings.port} is unavailable on the Orange host.") from exc


@router.get("/api/admin/system/listener")
def get_listener_settings(request: Request, _=Depends(verify_admin)):
    try:
        active = _active_listener(request)
        pending = listener.configured_settings(fallback=active)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(500, "Orange could not read the listener settings.") from exc
    return _listener_status(pending, active)


def _listener_status(pending, active):
    return {"active": asdict(active), "pending": asdict(pending), "managed": bool(os.environ.get("ORANGE_RUNNING_PORT")),
            "team_owner_exists": team.has_active_owner(), "needs_launcher_relaunch": listener.needs_launcher_relaunch(pending)}


def _parse_listener_change(payload, request, *, creating_owner=False):
    if not isinstance(payload, dict):
        raise HTTPException(422, "Provide an access mode and port.")
    active = _active_listener(request)
    mode = payload.get("mode")
    try:
        settings = listener.ListenerSettings(mode, payload.get("port"),
                                             payload.get("allow_lan_http", mode != "local" and active.allow_lan_http))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _validate_listener_change(settings, active, creating_owner=creating_owner)
    return settings, active


def _save_listener_change(settings, active):
    try:
        listener.save_settings(settings)
    except OSError as exc:
        raise HTTPException(500, "Orange could not save the listener settings.") from exc
    return _listener_status(settings, active)


@router.put("/api/admin/system/listener")
def update_listener_settings(payload: dict, request: Request, _=Depends(verify_admin)):
    return _save_listener_change(*_parse_listener_change(payload, request))


@router.get("/api/admin/media")
async def get_admin_media(_=Depends(verify_admin), request: Request = None, response: Response = None):
    servers = get_comfy_servers()

    async def fetch_history(url: str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.get(f"{url}/history")
                if res.status_code == 200:
                    return res.json()
            except Exception:
                pass
        return {}

    results = await asyncio.gather(*(fetch_history(s.get("url")) for s in servers))

    hist_data = {}
    for result in results:
        hist_data.update(result)

    usage_logs = {}
    try:
        with sqlite3.connect(get_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT prompt_id, client_ip, tool_id, prompt, timestamp, backend_url "
                    "FROM usage WHERE prompt_id IS NOT NULL"
                )
                for row in cursor.fetchall():
                    usage_logs[row["prompt_id"]] = _html_safe_log(dict(row))
            except sqlite3.OperationalError:
                pass
    except Exception:
        pass

    media_items = []
    for prompt_id, data in reversed(list(hist_data.items())):
        outputs = data.get("outputs", {})
        for output_type in ("image", "video", "audio"):
            items = collect_media_outputs(outputs, output_type)
            if output_type == "video":
                # Keep animated GIF/WebP outputs as image cards, as before.
                items = [item for item in items if item["media_type"].startswith("video/")]
            if items:
                media_items.append(
                    {
                        "prompt_id": prompt_id,
                        "filename": items[0]["filename"],
                        "type": output_type,
                        "analytics": usage_logs.get(prompt_id),
                    }
                )

    from app.core.media_jobs import list_completed
    for row in list_completed():
        items = json.loads(row.pop("outputs"))
        if items:
            media_items.append({"prompt_id": row["prompt_id"], "filename": items[0]["filename"], "type": row["type"], "analytics": _html_safe_log(row)})
    media_items.sort(key=lambda item: (item.get("analytics") or {}).get("timestamp", ""), reverse=True)
    if access.is_open_lan() and request is not None and response is not None:
        access.grant_gallery_access(response, request)
    return {"media": media_items}


@router.delete("/api/admin/media/session")
def clear_gallery_session(response: Response):
    response.delete_cookie(access.GALLERY_COOKIE, path="/api")
    return {"status": "ok"}


@router.get("/api/admin/usage")
def get_admin_usage(period: str = "all", export: bool = False, _=Depends(verify_analytics)):
    date_filter = PERIOD_FILTERS.get(period)
    if date_filter is None:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}. Valid: {', '.join(PERIOD_FILTERS.keys())}")
    aggregate_only = isinstance(_, dict) and _["role"] == "operator"
    if export and aggregate_only:
        raise HTTPException(403, "Usage exports are available to owners.")

    generations = f"""WITH generations AS (
        SELECT id, timestamp, tool_id, COALESCE(provider, 'comfyui') AS provider,
            model, COALESCE(status, 'queued') AS status
        FROM usage {date_filter or 'WHERE 1 = 1'}
          AND (prompt_id IS NULL OR id IN (
            SELECT MAX(id) FROM usage WHERE prompt_id IS NOT NULL GROUP BY prompt_id
          ))
    )"""
    try:
        with closing(sqlite3.connect(get_db_path())) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            limit = "" if export else "LIMIT 500"
            rows = [] if aggregate_only else [dict(row) for row in conn.execute(
                f"{generations} SELECT * FROM generations ORDER BY timestamp DESC, id DESC {limit}",
            )]
            groups = conn.execute(f"""{generations}
                SELECT tool_id, provider, status, COUNT(*) AS count
                FROM generations GROUP BY tool_id, provider, status
            """).fetchall()

        summary = {"logs": rows, "total": sum(row["count"] for row in groups)}
        for column, name in (("tool_id", "tools_summary"), ("provider", "provider_summary"), ("status", "status_summary")):
            counts = Counter()
            for row in groups:
                counts[row[column]] += row["count"]
            summary[name] = [{column: value, "count": count} for value, count in counts.most_common()]
        return summary
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/admin/huggingface-token")
def get_huggingface_token_status(_=Depends(verify_admin)):
    try:
        return huggingface.token_status()
    except OSError:
        raise HTTPException(status_code=503, detail=huggingface.CREDENTIAL_STORAGE_ERROR)


@router.post("/api/admin/huggingface-token")
def set_huggingface_token(payload: dict, _=Depends(verify_admin)):
    try:
        huggingface.save_token(payload.get("token"))
        return huggingface.token_status()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError:
        raise HTTPException(status_code=503, detail=huggingface.CREDENTIAL_STORAGE_ERROR)


@router.delete("/api/admin/huggingface-token")
def delete_huggingface_token(_=Depends(verify_admin)):
    try:
        huggingface.clear_token()
        return huggingface.token_status()
    except OSError:
        raise HTTPException(status_code=503, detail=huggingface.CREDENTIAL_STORAGE_ERROR)


@router.get("/api/admin/config")
def get_admin_config(_=Depends(verify_admin)):
    return load_config()


def _parse_team_owner(payload, listener_change):
    if listener_change is None or listener_change[0].mode != "team" or listener_change[1].mode == "team":
        raise HTTPException(400, "Choose Team mode to create its first owner.")
    if team.has_active_owner():
        raise HTTPException(409, "A Team owner already exists. Reopen General Settings to continue.")
    if not isinstance(payload, dict) or not isinstance(payload.get("handle"), str) or not isinstance(payload.get("password"), str):
        raise HTTPException(400, "Enter a username and password for the Team owner.")
    handle = team.normalize_handle(payload["handle"])
    password = payload["password"]
    team.validate_password(password)
    return handle, password


def _create_first_team_owner(handle, password):
    team.init_team()
    team.bootstrap_owner(handle, password)


async def _save_admin_settings(request, *, creating_owner=False):
    try:
        new_config = await request.json()
        if not isinstance(new_config, dict):
            raise HTTPException(400, "Provide an Orange settings object.")
        listener_change = None
        owner_credentials = None
        if "teamOwner" in new_config and not creating_owner:
            raise HTTPException(400, "Use Team setup to create an owner.")
        if "listenerSettings" in new_config:
            listener_change = _parse_listener_change(new_config.pop("listenerSettings"), request, creating_owner=creating_owner)
        if creating_owner:
            owner_credentials = _parse_team_owner(new_config.pop("teamOwner", None), listener_change)
        save_config(new_config)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if owner_credentials:
        try:
            await run_in_threadpool(_create_first_team_owner, *owner_credentials)
        except (OSError, sqlite3.Error) as exc:
            raise HTTPException(500, "Orange could not save the Team owner.") from exc
    result = {"status": "success"}
    if listener_change:
        result["listenerSettings"] = _save_listener_change(*listener_change)
    return result


@router.post("/api/admin/config")
async def update_admin_config(request: Request, _=Depends(verify_admin)):
    return await _save_admin_settings(request)


@router.post("/api/admin/system/team-setup")
async def setup_team_owner(request: Request, _=Depends(verify_admin)):
    return await _save_admin_settings(request, creating_owner=True)


@router.get("/api/admin/workflows")
def list_admin_workflows(_=Depends(verify_admin)):
    workflows_dir = os.path.join(PROJECT_ROOT, "workflows")
    files = [f for f in os.listdir(workflows_dir) if f.endswith(".json") and f != "workflows-config.json"]
    return {"files": files}


@router.get("/api/admin/workflows/{filename}")
def get_admin_workflow(filename: str, _=Depends(verify_admin)):
    safe_name = os.path.basename(filename)
    path = os.path.join(PROJECT_ROOT, "workflows", safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.delete("/api/admin/workflows/{filename}")
def delete_admin_workflow(filename: str, _=Depends(verify_admin)):
    safe_name = os.path.basename(filename)
    if safe_name == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Cannot delete config")

    path = os.path.join(PROJECT_ROOT, "workflows", safe_name)
    if os.path.exists(path):
        os.remove(path)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="File not found")


async def _delete_single_prompt(prompt_id: str, client: httpx.AsyncClient, all_servers: list):
    """Delete a prompt from ComfyUI history and the local usage database."""
    from app.core.media_jobs import delete_job
    try:
        if delete_job(prompt_id):
            return
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    backend_url = get_backend_for_prompt(prompt_id)
    target_urls = [backend_url] if backend_url else [s.get("url") for s in all_servers]

    for target_url in target_urls:
        if not target_url:
            continue
        try:
            await client.post(f"{target_url}/history", json={"delete": [prompt_id]})
        except Exception:
            pass
    delete_usage(prompt_id)


@router.post("/api/admin/bulk-delete")
async def bulk_delete_media(payload: dict, _=Depends(verify_admin)):
    prompt_ids = payload.get("prompt_ids", [])
    servers = get_comfy_servers()
    async with httpx.AsyncClient(timeout=5.0) as client:
        for prompt_id in prompt_ids:
            await _delete_single_prompt(prompt_id, client, servers)
    return {"status": "success", "deleted_count": len(prompt_ids)}


@router.delete("/api/admin/media/{prompt_id}")
async def delete_media(prompt_id: str, _=Depends(verify_admin)):
    servers = get_comfy_servers()
    async with httpx.AsyncClient(timeout=5.0) as client:
        await _delete_single_prompt(prompt_id, client, servers)
    return {"status": "success"}


@router.post("/api/admin/workflows/upload")
async def upload_admin_workflow(request: Request, file: UploadFile = File(...), _=Depends(verify_admin)):
    safe_name = os.path.basename(file.filename or "")
    if not safe_name.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are allowed")
    if safe_name == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Cannot overwrite config file")

    content = await _read_limited_upload(file, MAX_WORKFLOW_UPLOAD_BYTES, "Workflow")
    try:
        json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {exc}")

    path = os.path.join(PROJECT_ROOT, "workflows", safe_name)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return {"status": "success", "filename": safe_name}


@router.post("/api/admin/workflows/restore-defaults")
def admin_restore_defaults(overwrite: bool = False, _=Depends(verify_admin)):
    success = restore_defaults(overwrite=overwrite)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to restore defaults. Defaults folder might be missing.")
    return {"status": "success", "message": "Default workflows restored."}


@router.get("/api/admin/db/backup")
def backup_db(_=Depends(verify_admin)):
    db_path = get_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database not found")
    return FileResponse(path=db_path, filename="usage_logs_backup.db", media_type="application/octet-stream")


@router.post("/api/admin/db/restore")
async def restore_db(request: Request, file: UploadFile = File(...), _=Depends(verify_admin)):
    if not (file.filename or "").lower().endswith(".db"):
        raise HTTPException(status_code=400, detail="Only .db files are allowed")

    db_path = get_db_path()
    content = await _read_limited_upload(file, MAX_DB_RESTORE_BYTES, "Database backup")
    tmp_path = db_path + ".upload_tmp"

    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        with sqlite3.connect(tmp_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(usage)")
            columns = {row[1] for row in cursor.fetchall()}
            required_columns = {"id", "timestamp", "client_ip", "tool_id", "prompt"}
            if not required_columns.issubset(columns):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid database schema. Missing columns: {required_columns - columns}",
                )
    except sqlite3.DatabaseError as exc:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid SQLite database: {exc}")

    if os.path.exists(db_path):
        shutil.copy2(db_path, db_path + ".bak")
    shutil.move(tmp_path, db_path)
    return {"status": "success"}


@router.post("/api/admin/llm/models")
async def get_llm_models(payload: dict, _=Depends(verify_admin)):
    provider = payload.get("provider", "").lower()
    base_url = payload.get("baseUrl")
    api_key = payload.get("apiKey")

    resolved_key = None
    if provider == "openai":
        resolved_key = os.environ.get("OPENAI_API_KEY")
    elif provider == "gemini":
        resolved_key = os.environ.get("GEMINI_API_KEY")
    elif provider == "anthropic":
        resolved_key = os.environ.get("ANTHROPIC_API_KEY")
    if not resolved_key and api_key:
        resolved_key = api_key

    models = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "ollama":
                target_url = f"{base_url.rstrip('/')}/api/tags" if base_url else "http://127.0.0.1:11434/api/tags"
                res = await client.get(target_url)
                if res.status_code == 200:
                    models = [m["name"] for m in res.json().get("models", [])]
            elif provider == "openai":
                target_url = f"{base_url.rstrip('/')}/models" if base_url else "https://api.openai.com/v1/models"
                headers = {"Authorization": f"Bearer {resolved_key}"} if resolved_key else {}
                res = await client.get(target_url, headers=headers)
                if res.status_code == 200:
                    models = [m["id"] for m in res.json().get("data", [])]
            elif provider == "gemini":
                if resolved_key:
                    url_base = base_url.rstrip("/") if base_url else "https://generativelanguage.googleapis.com"
                    res = await client.get(f"{url_base}/v1beta/models?key={resolved_key}")
                    if res.status_code == 200:
                        models = [m["name"].replace("models/", "") for m in res.json().get("models", [])]
                if not models:
                    models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp", "gemini-2.5-flash", "gemini-2.5-pro"]
            elif provider == "anthropic":
                models = ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch models: {exc}")

    return {"models": models}


@router.get("/api/admin/prompts/{tool_id}")
def get_admin_prompt(tool_id: str, _=Depends(verify_admin)):
    if not re.match(r"^[a-zA-Z0-9_\-]+$", tool_id):
        raise HTTPException(status_code=400, detail="Invalid tool ID format")
    return {"prompt": get_system_prompt(tool_id)}


@router.post("/api/admin/prompts/{tool_id}")
def save_admin_prompt(tool_id: str, payload: dict, _=Depends(verify_admin)):
    if not re.match(r"^[a-zA-Z0-9_\-]+$", tool_id):
        raise HTTPException(status_code=400, detail="Invalid tool ID format")
    prompt = payload.get("prompt", "")

    prompts_dir = os.path.join(PROJECT_ROOT, "workflows", "prompts")
    os.makedirs(prompts_dir, exist_ok=True)
    file_path = os.path.join(prompts_dir, f"{tool_id}.txt")

    if not prompt.strip() and tool_id.lower() != "global":
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return {"status": "success", "message": "Prompt override removed."}

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(prompt)
        return {"status": "success", "message": "Prompt saved successfully."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save prompt: {exc}")
