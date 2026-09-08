from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.core.backends import get_backend_client
from app.core.database import get_backend_for_prompt
from app.core.outputs import collect_media_outputs, extract_text_output, guess_media_type
from app.core.utils import strip_metadata

router = APIRouter()

ALLOWED_OUTPUT_TYPES = {"image", "video", "audio", "text"}


async def _load_prompt_history(prompt_id: str):
    target_url = get_backend_for_prompt(prompt_id)
    if not target_url:
        raise HTTPException(status_code=404, detail="Generation backend is unknown for this prompt.")
    target_url = target_url.rstrip("/")

    client = await get_backend_client()
    try:
        response = await client.get(f"{target_url}/history/{prompt_id}", timeout=30.0)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach the generation backend.")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Generation history was not found.")

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Generation backend returned invalid history data.")

    record = payload.get(prompt_id) if isinstance(payload, dict) else None
    if not isinstance(record, dict):
        raise HTTPException(status_code=404, detail="Generation is not complete or did not produce output.")
    outputs = record.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}
    return target_url, outputs


@router.get("/api/outputs")
async def list_outputs(prompt_id: str, type: str = Query("image")):
    output_type = type.lower()
    if output_type not in ALLOWED_OUTPUT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported output type.")

    _, outputs = await _load_prompt_history(prompt_id)
    if output_type == "text":
        text = extract_text_output(outputs)
        return {"count": 1 if text is not None else 0, "text": text}

    items = collect_media_outputs(outputs, output_type)
    return {"count": len(items), "type": output_type, "items": items}


@router.get("/api/output")
@router.get("/api/media")
async def get_media(prompt_id: str, type: str = Query("image"), index: int = Query(0, ge=0)):
    output_type = type.lower()
    if output_type not in ALLOWED_OUTPUT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported output type.")

    target_url, outputs = await _load_prompt_history(prompt_id)
    if output_type == "text":
        text = extract_text_output(outputs)
        if text is None:
            raise HTTPException(status_code=404, detail="No text output found for this generation.")
        return {"text": text}

    items = collect_media_outputs(outputs, output_type)
    if index >= len(items):
        raise HTTPException(status_code=404, detail=f"Output {index + 1} was not found.")
    item = items[index]

    client = await get_backend_client()
    try:
        response = await client.get(
            f"{target_url}/view",
            params={
                "filename": item["filename"],
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
            },
            timeout=30.0,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not fetch output from the generation backend.")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Generation backend could not return this output.")

    raw_bytes = response.content
    response_type = response.headers.get("content-type")
    media_type = guess_media_type(item["filename"], response_type)

    if media_type.startswith("image/"):
        try:
            clean_bytes, clean_type = strip_metadata(raw_bytes)
            raw_bytes = clean_bytes
            media_type = clean_type or media_type
        except Exception:
            pass

    safe_filename = quote(item["filename"], safe="")
    headers = {"Content-Disposition": f"inline; filename*=UTF-8''{safe_filename}"}
    return Response(content=raw_bytes, media_type=media_type, headers=headers)


@router.get("/api/image")
async def get_image(prompt_id: str, index: int = Query(0, ge=0)):
    return await get_media(prompt_id=prompt_id, type="image", index=index)
