import asyncio
import io
import os
import random
import uuid

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image, UnidentifiedImageError

from app.core.backends import decrement_active, get_best_backend, increment_active
from app.core.config import get_base_workflow, get_comfy_servers, get_system_prompt, get_tool_settings, load_config
from app.core.database import get_backend_for_prompt, log_usage
from app.core.llm import call_llm
from app.core.utils import strip_metadata

router = APIRouter()

MAX_UPLOAD_MB = int(os.environ.get("ORANGE_MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_PROMPT_CHARS = int(os.environ.get("ORANGE_MAX_PROMPT_CHARS", "10000"))
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def get_comfy_url():
    """Fallback: returns the highest-priority configured server URL."""
    servers = get_comfy_servers()
    return servers[0].get("url") if servers else "http://127.0.0.1:8188"


async def _read_validated_image(upload_file: UploadFile) -> tuple[str, bytes, str]:
    """Read an uploaded image with size/type validation and a safe filename."""
    if upload_file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image format. Use JPEG, PNG, WebP, or GIF.")

    await upload_file.seek(0)
    data = bytearray()
    while True:
        chunk = await upload_file.read(1024 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Image exceeds the {MAX_UPLOAD_MB} MB upload limit.")

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.")

    filename = os.path.basename(upload_file.filename or "upload.png") or "upload.png"
    return filename, bytes(data), upload_file.content_type


async def _upload_image_to_comfy(upload_file: UploadFile, target_url: str) -> str:
    """Upload an image file to a specific ComfyUI backend and return its server-side filename."""
    filename, image_bytes, content_type = await _read_validated_image(upload_file)
    async with httpx.AsyncClient(timeout=30.0) as client:
        files = {"image": (filename, image_bytes, content_type)}
        res = await client.post(f"{target_url}/upload/image", files=files)
        if res.status_code != 200:
            raise RuntimeError("Failed to upload image to ComfyUI backend")
        return res.json().get("name")


@router.post("/api/generate")
async def generate(
    request: Request,
    tool_id: str = Form(...),
    prompt: str = Form(None),
    aspect_ratio: str = Form(None),
    image: UploadFile = File(None),
    image2: UploadFile = File(None),
):
    client_ip = request.client.host if request.client else "unknown"

    if prompt and len(prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail=f"Prompt exceeds the {MAX_PROMPT_CHARS} character limit.")

    tool = get_tool_settings(tool_id)
    if not tool:
        raise HTTPException(status_code=400, detail="Invalid tool ID")

    mapping = tool.get("nodeMapping", {})
    workflow = get_base_workflow(tool.get("workflowFile"))

    if mapping.get("prompt") and not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required for this tool")
    if mapping.get("image") and not image:
        raise HTTPException(status_code=400, detail="Image is required for this tool")
    if mapping.get("image2") and not image2:
        raise HTTPException(status_code=400, detail="Second image is required for this tool")

    client_id = str(uuid.uuid4())
    exclude_urls = []

    while True:
        target_url = await get_best_backend(exclude_urls=exclude_urls)
        if not target_url:
            raise HTTPException(status_code=503, detail="No healthy ComfyUI servers available.")

        increment_active(target_url)
        try:
            uploaded_image_name = None
            if image and mapping.get("image"):
                uploaded_image_name = await _upload_image_to_comfy(image, target_url)

            uploaded_image2_name = None
            if image2 and mapping.get("image2"):
                uploaded_image2_name = await _upload_image_to_comfy(image2, target_url)

            if prompt and mapping.get("prompt"):
                p_map = mapping["prompt"]
                workflow[p_map["nodeId"]]["inputs"][p_map["field"]] = prompt

            if uploaded_image_name and mapping.get("image"):
                i_map = mapping["image"]
                workflow[i_map["nodeId"]]["inputs"][i_map["field"]] = uploaded_image_name

            if uploaded_image2_name and mapping.get("image2"):
                i2_map = mapping["image2"]
                workflow[i2_map["nodeId"]]["inputs"][i2_map["field"]] = uploaded_image2_name

            if aspect_ratio and mapping.get("width") and mapping.get("height"):
                current_config = load_config()
                ar_config = tool.get("aspectRatios", current_config.get("aspectRatios", {})).get(aspect_ratio)
                if ar_config:
                    w_map = mapping["width"]
                    h_map = mapping["height"]
                    workflow[w_map["nodeId"]]["inputs"][w_map["field"]] = ar_config["width"]
                    workflow[h_map["nodeId"]]["inputs"][h_map["field"]] = ar_config["height"]

            if mapping.get("seed") and mapping["seed"].get("generateRandom"):
                s_map = mapping["seed"]
                workflow[s_map["nodeId"]]["inputs"][s_map["field"]] = random.randint(1, 1125899906)

            payload = {"prompt": workflow, "client_id": client_id}
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(f"{target_url}/prompt", json=payload)
                if res.status_code != 200:
                    raise RuntimeError("Failed to queue generation in ComfyUI")
                data = res.json()

            break
        except HTTPException:
            decrement_active(target_url)
            raise
        except Exception as exc:
            print(f"Server {target_url} failed: {exc}. Retrying next...")
            exclude_urls.append(target_url)
            decrement_active(target_url)

    asyncio.get_running_loop().call_later(2.0, decrement_active, target_url)

    server_priority = next(
        (s.get("priority", 1) for s in get_comfy_servers() if s.get("url") == target_url),
        1,
    )

    log_usage(client_ip, tool_id, prompt, prompt_id=data.get("prompt_id"), backend_url=target_url)

    return {
        "prompt_id": data.get("prompt_id"),
        "client_id": client_id,
        "server_priority": server_priority,
    }


@router.get("/api/output")
async def get_output(prompt_id: str, type: str = "image"):
    """Generalized output endpoint for image, video, audio, or text output."""
    target_url = get_backend_for_prompt(prompt_id) or get_comfy_url()

    async with httpx.AsyncClient(timeout=30.0) as client:
        hist_res = await client.get(f"{target_url}/history/{prompt_id}")
        if hist_res.status_code != 200:
            raise HTTPException(status_code=404, detail="History not found")

        hist_data = hist_res.json()
        if prompt_id not in hist_data:
            raise HTTPException(status_code=404, detail="Prompt ID not generated yet or failed")

        outputs = hist_data[prompt_id].get("outputs", {})
        file_info = None

        if type == "video":
            for output_data in outputs.values():
                for key in ["gifs", "video", "images"]:
                    items = output_data.get(key, [])
                    if items:
                        file_info = items[0]
                        break
                if file_info:
                    break
        elif type == "audio":
            for output_data in outputs.values():
                audios = output_data.get("audio", [])
                if audios:
                    file_info = audios[0]
                    break
        elif type == "text":
            for output_data in outputs.values():
                for key in ["text", "string", "messages"]:
                    txt = output_data.get(key)
                    if txt:
                        final_text = txt[0] if isinstance(txt, list) else txt
                        return {"text": final_text}
            raise HTTPException(status_code=404, detail="No text output found for prompt")
        else:
            for output_data in outputs.values():
                for key in ["images", "gifs"]:
                    items = output_data.get(key, [])
                    if items:
                        file_info = items[0]
                        break
                if file_info:
                    break

        if not file_info:
            raise HTTPException(status_code=404, detail=f"No {type} output found for prompt")

        view_url = (
            f"{target_url}/view?filename={file_info['filename']}"
            f"&subfolder={file_info.get('subfolder', '')}&type={file_info.get('type', 'output')}"
        )
        file_res = await client.get(view_url)
        if file_res.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Failed to fetch {type} from ComfyUI backend")

        raw_bytes = file_res.content

        if type == "image":
            try:
                clean_bytes, media_type = strip_metadata(raw_bytes)
                return StreamingResponse(io.BytesIO(clean_bytes), media_type=media_type)
            except Exception:
                content_type = file_res.headers.get("content-type", "image/png").split(";", 1)[0]
                return StreamingResponse(io.BytesIO(raw_bytes), media_type=content_type)
        if type == "video":
            fname = file_info["filename"].lower()
            if fname.endswith(".webp"):
                media_type = "image/webp"
            elif fname.endswith(".gif"):
                media_type = "image/gif"
            elif fname.endswith(".webm"):
                media_type = "video/webm"
            elif fname.endswith(".mkv"):
                media_type = "video/x-matroska"
            elif fname.endswith(".mov"):
                media_type = "video/quicktime"
            else:
                media_type = "video/mp4"
            return StreamingResponse(io.BytesIO(raw_bytes), media_type=media_type)
        if type == "audio":
            fname = file_info["filename"].lower()
            if fname.endswith(".wav"):
                media_type = "audio/wav"
            elif fname.endswith(".mp3"):
                media_type = "audio/mpeg"
            elif fname.endswith(".ogg"):
                media_type = "audio/ogg"
            elif fname.endswith(".m4a"):
                media_type = "audio/mp4"
            else:
                media_type = "audio/flac"
            return StreamingResponse(io.BytesIO(raw_bytes), media_type=media_type)


@router.get("/api/image")
async def get_image(prompt_id: str):
    """Backward-compatible alias for /api/output?type=image."""
    return await get_output(prompt_id, type="image")


@router.post("/api/enhance-prompt")
async def enhance_prompt(prompt: str = Form(...), tool_id: str = Form(...)):
    if len(prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail=f"Prompt exceeds the {MAX_PROMPT_CHARS} character limit.")

    tool = get_tool_settings(tool_id)
    if not tool:
        raise HTTPException(status_code=400, detail="Invalid tool ID")

    mapping = tool.get("nodeMapping", {})
    if not mapping.get("prompt"):
        raise HTTPException(
            status_code=400,
            detail="Prompt enhancement is not supported for this tool (no prompt input mapped).",
        )

    config = load_config()
    global_llm = config.get("llm", {})
    tool_enhance = tool.get("promptEnhance", {})

    if not global_llm.get("enabled", False):
        raise HTTPException(status_code=400, detail="Prompt enhancement is disabled globally.")
    if not tool_enhance.get("enabled", True):
        raise HTTPException(status_code=400, detail="Prompt enhancement is disabled for this tool.")

    provider = tool_enhance.get("provider", global_llm.get("provider", "openai"))
    base_url = tool_enhance.get("baseUrl", global_llm.get("baseUrl"))
    api_key = tool_enhance.get("apiKey", global_llm.get("apiKey"))
    model = tool_enhance.get("model", global_llm.get("model"))
    system_prompt = get_system_prompt(tool_id)

    if not provider or not model or not system_prompt:
        raise HTTPException(
            status_code=400,
            detail="Prompt enhancement is not fully configured. Please configure it in General Settings.",
        )

    try:
        enhanced = await call_llm(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            prompt=prompt,
        )
        return {"enhanced_prompt": enhanced}
    except Exception as exc:
        import traceback

        traceback.print_exc()
        error_msg = str(exc) or "Unknown error occurred"
        raise HTTPException(status_code=500, detail=f"LLM Error ({type(exc).__name__}): {error_msg}")
