import os
import sqlite3
import subprocess
import shutil
import json
from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse

from app.core.config import load_config, save_config, PROJECT_ROOT
from app.core.database import get_db_path

router = APIRouter()

async def verify_admin(authorization: str = Header(None)):
    config = load_config()
    expected_key = config.get("adminKey", "orangeadmin")
    if not authorization or authorization != f"Bearer {expected_key}":
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid admin key")
    return True

PERIOD_FILTERS = {
    "all":       "",
    "weekly":    "WHERE timestamp >= datetime('now', '-7 days')",
    "monthly":   "WHERE timestamp >= datetime('now', '-1 month')",
    "quarterly": "WHERE timestamp >= datetime('now', '-3 months')",
    "yearly":    "WHERE timestamp >= datetime('now', '-1 year')",
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
            "remote_version": remote[:7]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check updates: {str(e)}")

@router.post("/api/admin/system/update")
def apply_update(_=Depends(verify_admin)):
    try:
        subprocess.run(["git", "pull"], check=True, capture_output=True, cwd=PROJECT_ROOT)
        return {"status": "success", "message": "Updated to latest version. Please restart the server."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update: {str(e)}")

@router.post("/api/admin/system/restart")
def restart_server(_=Depends(verify_admin)):
    try:
        with open(os.path.join(PROJECT_ROOT, "RESTART_REQUIRED"), "w") as f:
            f.write("1")
        os._exit(0)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart: {str(e)}")

@router.get("/api/admin/usage")
def get_admin_usage(period: str = "all", _=Depends(verify_admin)):
    date_filter = PERIOD_FILTERS.get(period)
    if date_filter is None:
        raise HTTPException(status_code=400, detail=f"Invalid period: {period}. Valid: {', '.join(PERIOD_FILTERS.keys())}")

    try:
        with sqlite3.connect(get_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(f"SELECT * FROM usage {date_filter} ORDER BY timestamp DESC LIMIT 500")
            rows = [dict(row) for row in c.fetchall()]
            
            c.execute(f"SELECT tool_id, COUNT(*) as count FROM usage {date_filter} GROUP BY tool_id")
            tools_summary = [dict(row) for row in c.fetchall()]
            
            c.execute(f"SELECT client_ip, COUNT(*) as count FROM usage {date_filter} GROUP BY client_ip")
            ip_summary = [dict(row) for row in c.fetchall()]
        
        return {
            "logs": rows,
            "tools_summary": tools_summary,
            "ip_summary": ip_summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/admin/config")
def get_admin_config(_=Depends(verify_admin)):
    return load_config()

@router.post("/api/admin/config")
async def update_admin_config(request: Request, _=Depends(verify_admin)):
    try:
        new_config = await request.json()
        save_config(new_config)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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

@router.post("/api/admin/workflows/upload")
async def upload_admin_workflow(request: Request, file: UploadFile = File(...), _=Depends(verify_admin)):
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are allowed")
        
    safe_name = os.path.basename(file.filename)
    if safe_name == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Cannot overwrite config file")
        
    path = os.path.join(PROJECT_ROOT, "workflows", safe_name)
    content = await file.read()
    try:
        json.loads(content)
        with open(path, "wb") as f:
            f.write(content)
        return {"status": "success", "filename": safe_name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")

@router.get("/api/admin/db/backup")
def backup_db(_=Depends(verify_admin)):
    db_path = get_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database not found")
        
    return FileResponse(path=db_path, filename="usage_logs_backup.db", media_type="application/octet-stream")

@router.post("/api/admin/db/restore")
async def restore_db(request: Request, file: UploadFile = File(...), _=Depends(verify_admin)):
    if not file.filename.endswith(".db"):
        raise HTTPException(status_code=400, detail="Only .db files are allowed")
        
    db_path = get_db_path()
    content = await file.read()
    tmp_path = db_path + ".upload_tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(usage)")
        columns = {row[1] for row in cursor.fetchall()}
        required_columns = {"id", "timestamp", "client_ip", "tool_id", "prompt"}
        if not required_columns.issubset(columns):
            conn.close()
            raise HTTPException(status_code=400, detail=f"Invalid database schema. Missing columns: {required_columns - columns}")
        conn.close()
    except sqlite3.DatabaseError as e:
        raise HTTPException(status_code=400, detail=f"Uploaded file is not a valid SQLite database: {e}")
    finally:
        pass
    
    if os.path.exists(db_path):
        backup_path = db_path + ".bak"
        shutil.copy2(db_path, backup_path)
    
    shutil.move(tmp_path, db_path)
    return {"status": "success"}
