import io
import mimetypes
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.api.admin import verify_admin
from app.core.config import PROJECT_ROOT
from app.core.workflow_assets import (
    asset_directory,
    list_workflow_assets,
    safe_asset_name,
)

router = APIRouter()

MAX_ASSET_MB = int(os.environ.get("ORANGE_MAX_WORKFLOW_ASSET_MB", "50"))
MAX_ASSET_BYTES = MAX_ASSET_MB * 1024 * 1024
ALLOWED_ASSET_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_ASSET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _ensure_workflow_exists(workflow_file: str) -> str:
    name = os.path.basename(str(workflow_file or "").strip())
    if not name or name != str(workflow_file or "").strip() or not name.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Invalid workflow filename")
    if name == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Config file cannot have workflow assets")

    candidates = [
        os.path.join(PROJECT_ROOT, "workflows", name),
        os.path.join(PROJECT_ROOT, "workflows", "defaults", name),
    ]
    if not any(os.path.isfile(path) for path in candidates):
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' was not found")
    return name


async def _read_limited(file: UploadFile) -> bytes:
    data = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_ASSET_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Workflow asset exceeds the {MAX_ASSET_MB} MB upload limit",
            )
    if not data:
        raise HTTPException(status_code=400, detail="Workflow asset is empty")
    return bytes(data)


def _validate_image(name: str, content_type: str, data: bytes) -> None:
    extension = os.path.splitext(name)[1].lower()
    if extension not in ALLOWED_ASSET_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Use JPEG, PNG, WebP, or GIF workflow assets")

    normalized_type = (content_type or "").split(";", 1)[0].lower()
    guessed_type = mimetypes.guess_type(name)[0]
    if normalized_type and normalized_type not in ALLOWED_ASSET_TYPES:
        raise HTTPException(status_code=400, detail="Use JPEG, PNG, WebP, or GIF workflow assets")
    if guessed_type and guessed_type not in ALLOWED_ASSET_TYPES:
        raise HTTPException(status_code=400, detail="Use JPEG, PNG, WebP, or GIF workflow assets")

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image asset: {exc}")


@router.get("/api/admin/workflows/{workflow_file}/assets")
def get_workflow_assets(workflow_file: str, _=Depends(verify_admin)):
    name = _ensure_workflow_exists(workflow_file)
    return {"workflow": name, "assets": list_workflow_assets(name)}


@router.post("/api/admin/workflows/{workflow_file}/assets")
async def upload_workflow_asset(
    workflow_file: str,
    file: UploadFile = File(...),
    _=Depends(verify_admin),
):
    workflow_name = _ensure_workflow_exists(workflow_file)
    try:
        asset_name = safe_asset_name(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    data = await _read_limited(file)
    _validate_image(asset_name, file.content_type or "", data)

    directory = asset_directory(workflow_name, create=True)
    destination = os.path.join(directory, asset_name)
    temp_path = destination + ".tmp"
    try:
        with open(temp_path, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass

    return {
        "status": "success",
        "workflow": workflow_name,
        "asset": asset_name,
        "assets": list_workflow_assets(workflow_name),
    }


@router.delete("/api/admin/workflows/{workflow_file}/assets/{asset_name}")
def delete_workflow_asset(workflow_file: str, asset_name: str, _=Depends(verify_admin)):
    workflow_name = _ensure_workflow_exists(workflow_file)
    try:
        safe_name = safe_asset_name(asset_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    path = os.path.join(asset_directory(workflow_name), safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Workflow asset not found")
    os.remove(path)
    return {
        "status": "success",
        "workflow": workflow_name,
        "assets": list_workflow_assets(workflow_name),
    }
