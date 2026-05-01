import time
import random
import uuid
import io
from typing import Dict
import httpx
from fastapi import APIRouter, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_tool_settings, get_base_workflow, load_config
from app.core.database import log_usage
from app.core.utils import strip_metadata

router = APIRouter()

# Rate Limiting State
last_generate_time: Dict[str, float] = {}
COOLDOWN_SECONDS = 5.0

def get_comfy_url():
    return load_config().get("comfyServerUrl", "http://127.0.0.1:8188")

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
    now = time.time()
    
    # Cooldown Logic
    if client_ip in last_generate_time:
        time_since = now - last_generate_time[client_ip]
        if time_since < COOLDOWN_SECONDS:
            raise HTTPException(status_code=429, detail=f"Please wait {int(COOLDOWN_SECONDS - time_since)} more seconds before generating.")
            
    last_generate_time[client_ip] = now

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
    
    # 1. Upload Images to ComfyUI if required
    async def upload_image_to_comfy(upload_file: UploadFile) -> str:
        try:
            async with httpx.AsyncClient() as client:
                files = {'image': (upload_file.filename, await upload_file.read(), upload_file.content_type)}
                res = await client.post(f"{get_comfy_url()}/upload/image", files=files)
                if res.status_code != 200:
                    raise HTTPException(status_code=500, detail="Failed to upload image to ComfyUI backend")
                return res.json().get("name")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Could not connect to ComfyUI server for upload. Is it running on the correct port?")

    uploaded_image_name = None
    if image and mapping.get("image"):
        uploaded_image_name = await upload_image_to_comfy(image)

    uploaded_image2_name = None
    if image2 and mapping.get("image2"):
        uploaded_image2_name = await upload_image_to_comfy(image2)
            
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

    client_id = str(uuid.uuid4())

    # 3. Trigger Generation
    payload = {"prompt": workflow, "client_id": client_id}
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{get_comfy_url()}/prompt", json=payload)
            if res.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to queue generation in ComfyUI")
            data = res.json()
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail=f"Could not connect to ComfyUI server at {get_comfy_url()}. Is it running?")
        
    # Log successful generation request
    log_usage(client_ip, tool_id, prompt)
    
    return {"prompt_id": data.get("prompt_id"), "client_id": client_id}

@router.get("/api/output")
async def get_output(prompt_id: str, type: str = "image"):
    """
    Generalized output endpoint. Fetches the result from ComfyUI history.
    type: 'image', 'video', or 'audio'
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        hist_res = await client.get(f"{get_comfy_url()}/history/{prompt_id}")
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
            
        view_url = f"{get_comfy_url()}/view?filename={file_info['filename']}&subfolder={file_info.get('subfolder', '')}&type={file_info.get('type', 'output')}"
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
