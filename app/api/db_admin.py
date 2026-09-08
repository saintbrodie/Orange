import os
import sqlite3
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.api.admin import MAX_DB_RESTORE_BYTES, _read_limited_upload, verify_admin
from app.core.database import backup_database, get_db_path, restore_database, validate_database

router = APIRouter()


def _remove_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


@router.get("/api/admin/db/backup")
def backup_db(_=Depends(verify_admin)):
    db_path = get_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Database not found")

    handle = tempfile.NamedTemporaryFile(prefix="orange-backup-", suffix=".db", delete=False)
    backup_path = handle.name
    handle.close()
    try:
        backup_database(backup_path)
    except Exception as exc:
        _remove_file(backup_path)
        raise HTTPException(status_code=500, detail=f"Failed to create database backup: {exc}")

    return FileResponse(
        path=backup_path,
        filename="usage_logs_backup.db",
        media_type="application/octet-stream",
        background=BackgroundTask(_remove_file, backup_path),
    )


@router.post("/api/admin/db/restore")
async def restore_db(file: UploadFile = File(...), _=Depends(verify_admin)):
    if not (file.filename or "").lower().endswith(".db"):
        raise HTTPException(status_code=400, detail="Only .db files are allowed")

    content = await _read_limited_upload(file, MAX_DB_RESTORE_BYTES, "Database backup")
    handle = tempfile.NamedTemporaryFile(prefix="orange-restore-", suffix=".db", delete=False)
    upload_path = handle.name
    try:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()

    try:
        try:
            validate_database(upload_path)
        except (sqlite3.DatabaseError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Orange database backup: {exc}")

        backup_path = get_db_path() + ".bak"
        try:
            restore_database(upload_path, backup_path=backup_path)
        except (sqlite3.DatabaseError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"Could not restore database backup: {exc}")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Database restore failed: {exc}")
    finally:
        _remove_file(upload_path)

    return {"status": "success"}
