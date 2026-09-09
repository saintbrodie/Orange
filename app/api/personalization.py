import io
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image

from app.api.admin import verify_admin
from app.core.personalization import (
    BRANDING_DIR,
    branding_path,
    clear_branding,
    load_personalization,
    save_personalization,
)
from app.core.utils import strip_metadata

router = APIRouter()

MAX_BRANDING_BYTES = 3 * 1024 * 1024
MAX_BRANDING_DIMENSION = 4096
FORMAT_EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}


async def _read_branding_upload(file: UploadFile) -> tuple[bytes, str]:
    data = bytearray()
    while True:
        chunk = await file.read(512 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_BRANDING_BYTES:
            raise HTTPException(status_code=413, detail="Branding image exceeds the 3 MB upload limit.")

    raw = bytes(data)
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
    except Exception:
        raise HTTPException(status_code=400, detail="Branding file must be a valid PNG, JPEG, or WebP image.")

    if image_format not in FORMAT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Branding file must be PNG, JPEG, or WebP.")
    if width < 1 or height < 1 or width > MAX_BRANDING_DIMENSION or height > MAX_BRANDING_DIMENSION:
        raise HTTPException(status_code=400, detail="Branding image dimensions must be between 1 and 4096 pixels.")

    try:
        clean_bytes, media_type = strip_metadata(raw)
    except Exception:
        clean_bytes = raw
        media_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[image_format]
    clean_format = "PNG" if media_type == "image/png" else "JPEG" if media_type == "image/jpeg" else "WEBP"
    return clean_bytes, FORMAT_EXTENSIONS[clean_format]


def _public_payload() -> dict:
    config = load_personalization()
    return {
        **config,
        "brandingAssets": {
            "logo": "/api/branding/logo" if branding_path("logo") else None,
            "icon": "/api/branding/icon" if branding_path("icon") else None,
        },
    }


@router.get("/api/personalization")
def get_personalization_public():
    return _public_payload()


@router.get("/api/admin/personalization")
def get_personalization_admin(_=Depends(verify_admin)):
    return _public_payload()


@router.post("/api/admin/personalization")
async def update_personalization(request: Request, _=Depends(verify_admin)):
    try:
        data = await request.json()
        save_personalization(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="Could not save personalization settings.")
    return _public_payload()


@router.post("/api/admin/personalization/branding/{kind}")
async def upload_branding(kind: str, file: UploadFile = File(...), _=Depends(verify_admin)):
    if kind not in {"logo", "icon"}:
        raise HTTPException(status_code=404, detail="Unknown branding asset.")

    clean_bytes, extension = await _read_branding_upload(file)
    os.makedirs(BRANDING_DIR, exist_ok=True)
    clear_branding(kind)
    path = os.path.join(BRANDING_DIR, kind + extension)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "wb") as handle:
            handle.write(clean_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return _public_payload()


@router.delete("/api/admin/personalization/branding/{kind}")
def delete_branding(kind: str, _=Depends(verify_admin)):
    if kind not in {"logo", "icon"}:
        raise HTTPException(status_code=404, detail="Unknown branding asset.")
    clear_branding(kind)
    return _public_payload()


@router.get("/api/branding/{kind}")
def get_branding(kind: str):
    path = branding_path(kind)
    if not path:
        raise HTTPException(status_code=404, detail="Branding asset not found.")
    extension = Path(path).suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(extension, "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-cache"})
