import asyncio
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess

import httpx
from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.config import PROJECT_ROOT, get_comfy_servers, get_system_prompt, load_config, restore_defaults, save_config
from app.core.database import delete_usage, get_backend_for_prompt, get_db_path

router = APIRouter()

MAX_WORKFLOW_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DB_RESTORE_BYTES = 250 * 1024 * 1024


async def verify_admin(authorization: str = Header(None)):
    config = load_config()
    expected_key = config.get("adminKey", "orangeadmin")
    if not authorization or authorization != f"Bearer {expected_key}":
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid admin key")
    return True


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
    for key in ("prompt", "client_ip", "tool_id", "backend_url"):
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
def restart_server(_=Depends(verify_admin)):
    try:
        with open(os.path.join(PROJECT_ROOT, "RESTART_REQUIRED"), "w", encoding="utf-8") as f:
            f.write("1")
        os._exit(0)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to restart: {exc}")


@router.get("/api/admin/media")
async def get_admin_media(_=Depends(verify_admin)):
    servers = get_comfy_servers()
    if not servers:
        raise HTTPException(status_code=500, detail="No ComfyUI servers configured")

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
        types_added = set()
        for output_data in outputs.values():
            for media_key in ["images", "gifs", "video", "audio"]:
                if media_key in types_added:
                    continue
                items = output_data.get(media_key, [])
                if not items:
                    continue
                output_type = "image" if media_key in ["images", "gifs"] else media_key
                if output_type in types_added:
                    continue
                media_items.append(
                    {
                        "prompt_id": prompt_id,
                        "filename": items[0].get("filename"),
                        "type": output_type,
                        "analytics": usage_logs.get(prompt_id),
                    }
                )
                types_added.add(output_type)
                types_added.add(media_key)

    return {"media": media_items}


@router.get("/api/admin/usage")
def get_admin_usage(period: str = "all", export: bool = False, _=Depends(verify_admin)):
    date_filter = PERIOD_FILTERS.get(period)
    if date_filter is None:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}. Valid: {', '.join(PERIOD_FILTERS.keys())}")

    try:
        with sqlite3.connect(get_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if export:
                cursor.execute(f"SELECT * FROM usage {date_filter} ORDER BY timestamp DESC")
            else:
                cursor.execute(f"SELECT * FROM usage {date_filter} ORDER BY timestamp DESC LIMIT 500")
            rows = [dict(row) for row in cursor.fetchall()]
            if not export:
                rows = [_html_safe_log(row) for row in rows]

            cursor.execute(f"SELECT tool_id, COUNT(*) as count FROM usage {date_filter} GROUP BY tool_id")
            tools_summary = [dict(row) for row in cursor.fetchall()]

            cursor.execute(f"SELECT client_ip, COUNT(*) as count FROM usage {date_filter} GROUP BY client_ip")
            ip_summary = [dict(row) for row in cursor.fetchall()]

        return {"logs": rows, "tools_summary": tools_summary, "ip_summary": ip_summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/admin/config")
def get_admin_config(_=Depends(verify_admin)):
    return load_config()


@router.post("/api/admin/config")
async def update_admin_config(request: Request, _=Depends(verify_admin)):
    try:
        new_config = await request.json()
        save_config(new_config)
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
