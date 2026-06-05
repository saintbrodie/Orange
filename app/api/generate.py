import asyncio
import random
import uuid
import io
import httpx
from fastapi import APIRouter, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_tool_settings, get_base_workflow, load_config, get_comfy_servers, get_system_prompt
from app.core.llm import call_llm
from app.core.database import log_usage, get_backend_for_prompt
from app.core.utils import strip_metadata
from app.core.backends import get_best_backend, increment_active, decrement_active

router = APIRouter()


def get_comfy_url():
    """Fallback: returns the highest-priority configured server URL."""
    servers = get_comfy_servers()
    return servers[0].get("url") if servers else "http://127.0.0.1:8188"


async def _upload_image_to_comfy(upload_file: UploadFile, target_url: str) -> str:
    """Upload an image file to a specific ComfyUI backend and return its server-side filename."""
    await upload_file.seek(0)
    async with httpx.AsyncClient() as client:
        files = {'image': (upload_file.filename, await upload_file.read(), upload_file.content_type)}
        res = await client.post(f"{target_url}/upload/image", files=files)
        if res.status_code != 200:
            raise Exception("Failed to upload image to ComfyUI backend")
        return res.json().get("name")


@router.post("/api/generate")
async def generate(
    request: Request,
    tool_id: str = Form(...),
    prompt: str = Form(None),
    aspect_ratio: str = Form(None),
    image: UploadFile = File(None),
    image2: UploadFile = File(None)
):
    client_ip = request.client.host if request.client else "unknown"

    tool = get_tool_settings(tool_id)
    if not tool:
        raise HTTPException(status_code=400, detail="Invalid tool ID")

    mapping = tool.get("nodeMapping", {})
    workflow = get_base_workflow(tool.get("workflowFile"))

    # Validation based on mappings
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
            # 1. Upload Images to ComfyUI if required
            uploaded_image_name = None
            if image and mapping.get("image"):
                uploaded_image_name = await _upload_image_to_comfy(image, target_url)

            uploaded_image2_name = None
            if image2 and mapping.get("image2"):
                uploaded_image2_name = await _upload_image_to_comfy(image2, target_url)

            # 2. Map variables into the workflow
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
                arConfig = tool.get("aspectRatios", current_config.get("aspectRatios", {})).get(aspect_ratio)
                if arConfig:
                    w_map = mapping["width"]
                    h_map = mapping["height"]
                    workflow[w_map["nodeId"]]["inputs"][w_map["field"]] = arConfig["width"]
                    workflow[h_map["nodeId"]]["inputs"][h_map["field"]] = arConfig["height"]

            if mapping.get("seed") and mapping["seed"].get("generateRandom"):
                s_map = mapping["seed"]
                workflow[s_map["nodeId"]]["inputs"][s_map["field"]] = random.randint(1, 1125899906)

            # 3. Trigger Generation
            payload = {"prompt": workflow, "client_id": client_id}
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{target_url}/prompt", json=payload)
                if res.status_code != 200:
                    raise Exception("Failed to queue generation in ComfyUI")
                data = res.json()

            break  # Success — exit retry loop
        except Exception as e:
            print(f"Server {target_url} failed: {e}. Retrying next...")
            exclude_urls.append(target_url)
            decrement_active(target_url)  # Only decrement on failure

    # Keep in-flight count elevated briefly so back-to-back requests see this server as busy,
    # then release it once ComfyUI's own queue reflects the job.
    asyncio.get_event_loop().call_later(2.0, decrement_active, target_url)

    # Determine the priority number of the chosen server for the frontend display
    server_priority = next(
        (s.get("priority", 1) for s in get_comfy_servers() if s.get("url") == target_url),
        1
    )

    # Log successful generation request
    log_usage(client_ip, tool_id, prompt, prompt_id=data.get("prompt_id"), backend_url=target_url)

    return {
        "prompt_id": data.get("prompt_id"),
        "client_id": client_id,
        "server_priority": server_priority
    }


@router.get("/api/output")
async def get_output(prompt_id: str, type: str = "image"):
    """
    Generalized output endpoint. Fetches the result from ComfyUI history.
    type: 'image', 'video', or 'audio'
    """
    target_url = get_backend_for_prompt(prompt_id)
    if not target_url:
        target_url = get_comfy_url()  # Fallback to highest-priority server

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
            for node_id, output_data in outputs.items():
                for key in ["gifs", "video", "images"]:
                    items = output_data.get(key, [])
                    if items:
                        file_info = items[0]
                        break
                if file_info: break
        elif type == "audio":
            for node_id, output_data in outputs.items():
                audios = output_data.get("audio", [])
                if audios:
                    file_info = audios[0]
                    break
                if file_info: break
        elif type == "text":
            for node_id, output_data in outputs.items():
                for key in ["text", "string", "messages"]:
                    txt = output_data.get(key)
                    if txt:
                        final_text = txt[0] if isinstance(txt, list) else txt
                        return {"text": final_text}
            raise HTTPException(status_code=404, detail="No text output found for prompt")
        else:
            for node_id, output_data in outputs.items():
                for key in ["images", "gifs"]:
                    items = output_data.get(key, [])
                    if items:
                        file_info = items[0]
                        break
                if file_info: break

        if not file_info:
            raise HTTPException(status_code=404, detail=f"No {type} output found for prompt")

        view_url = f"{target_url}/view?filename={file_info['filename']}&subfolder={file_info.get('subfolder', '')}&type={file_info.get('type', 'output')}"
        file_res = await client.get(view_url)
        if file_res.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Failed to fetch {type} from ComfyUI backend")

        raw_bytes = file_res.content

        if type == "image":
            try:
                clean_bytes = strip_metadata(raw_bytes)
                return StreamingResponse(io.BytesIO(clean_bytes), media_type="image/jpeg")
            except Exception:
                return StreamingResponse(io.BytesIO(raw_bytes), media_type="image/png")
        elif type == "video":
            fname = file_info['filename'].lower()
            if fname.endswith('.webp'): media_type = "image/webp"
            elif fname.endswith('.gif'): media_type = "image/gif"
            elif fname.endswith('.webm'): media_type = "video/webm"
            elif fname.endswith('.mkv'): media_type = "video/x-matroska"
            elif fname.endswith('.mov'): media_type = "video/quicktime"
            else: media_type = "video/mp4"
            return StreamingResponse(io.BytesIO(raw_bytes), media_type=media_type)
        elif type == "audio":
            fname = file_info['filename'].lower()
            if fname.endswith('.wav'): media_type = "audio/wav"
            elif fname.endswith('.mp3'): media_type = "audio/mpeg"
            elif fname.endswith('.ogg'): media_type = "audio/ogg"
            elif fname.endswith('.m4a'): media_type = "audio/mp4"
            else: media_type = "audio/flac"
            return StreamingResponse(io.BytesIO(raw_bytes), media_type=media_type)


@router.get("/api/image")
async def get_image(prompt_id: str):
    """Backward-compatible alias for /api/output?type=image"""
    return await get_output(prompt_id, type="image")


@router.post("/api/enhance-prompt")
async def enhance_prompt(
    prompt: str = Form(...),
    tool_id: str = Form(...)
):
    tool = get_tool_settings(tool_id)
    if not tool:
        raise HTTPException(status_code=400, detail="Invalid tool ID")

    # Check if this tool maps a prompt input
    mapping = tool.get("nodeMapping", {})
    if not mapping.get("prompt"):
        raise HTTPException(
            status_code=400,
            detail="Prompt enhancement is not supported for this tool (no prompt input mapped)."
        )

    # Load configurations
    config = load_config()
    global_llm = config.get("llm", {})

    # Tool-specific overrides
    tool_enhance = tool.get("promptEnhance", {})

    # Check if enabled globally and not disabled in tool
    global_enabled = global_llm.get("enabled", False)
    tool_enabled = tool_enhance.get("enabled", True)

    if not global_enabled:
        raise HTTPException(status_code=400, detail="Prompt enhancement is disabled globally.")
    if not tool_enabled:
        raise HTTPException(status_code=400, detail="Prompt enhancement is disabled for this tool.")

    # Resolve settings
    provider = tool_enhance.get("provider", global_llm.get("provider", "openai"))
    base_url = tool_enhance.get("baseUrl", global_llm.get("baseUrl"))
    api_key = tool_enhance.get("apiKey", global_llm.get("apiKey"))
    model = tool_enhance.get("model", global_llm.get("model"))
    system_prompt = get_system_prompt(tool_id)

    if not provider or not model or not system_prompt:
        raise HTTPException(
            status_code=400,
            detail="Prompt enhancement is not fully configured. Please configure it in General Settings."
        )

    try:
        enhanced = await call_llm(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            prompt=prompt
        )
        return {"enhanced_prompt": enhanced}
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e) or "Unknown error occurred"
        raise HTTPException(status_code=500, detail=f"LLM Error ({type(e).__name__}): {error_msg}")

