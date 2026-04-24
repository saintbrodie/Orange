import os
import json
import random
import io
import asyncio
import httpx
import websockets
import uuid
import time
import base64
import sqlite3
from typing import Dict
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from configManager import load_config, save_config, get_tool_settings, get_base_workflow
from imageUtils import strip_metadata

app = FastAPI(title="ComfyUI Minimal Frontend")

# Initialize the SQLite database for logging usage
def init_db():
    conn = sqlite3.connect("usage_logs.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            client_ip TEXT,
            tool_id TEXT,
            prompt TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def log_usage(client_ip: str, tool_id: str, prompt: str = None):
    try:
        conn = sqlite3.connect("usage_logs.db")
        c = conn.cursor()
        c.execute("INSERT INTO usage (client_ip, tool_id, prompt) VALUES (?, ?, ?)", (client_ip, tool_id, prompt))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging usage: {e}")

# Rate Limiting State
last_generate_time: Dict[str, float] = {}
COOLDOWN_SECONDS = 5.0

def get_current_config():
    return load_config()

COMFY_URL = get_current_config().get("comfyServerUrl", "http://127.0.0.1:8188")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/workflows")
def get_workflows():
    current_config = get_current_config()
    return {
        "tools": current_config.get("tools", []),
        "aspectRatios": current_config.get("aspectRatios", {})
    }

@app.get("/api/health")
async def get_health():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{COMFY_URL}/system_stats")
            if res.status_code == 200:
                data = res.json()
                vram_warning = False
                devices = data.get("devices", [])
                if devices:
                    device = devices[0]
                    vram_free = device.get("vram_free", 1)
                    vram_total = device.get("vram_total", 1)
                    if vram_total > 0 and (vram_free / vram_total) < 0.05:
                        vram_warning = True
                return {"status": "ready", "vram_warning": vram_warning}
    except Exception:
        pass
    return JSONResponse(status_code=503, content={"status": "offline"})

@app.post("/api/generate")
async def generate(
    request: Request,
    tool_id: str = Form(...),
    prompt: str = Form(None),
    aspect_ratio: str = Form(None),
    image: UploadFile = File(None)
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
    
    # 1. Upload Image to ComfyUI if required
    uploaded_image_name = None
    if image and mapping.get("image"):
        try:
            async with httpx.AsyncClient() as client:
                files = {'image': (image.filename, await image.read(), image.content_type)}
                res = await client.post(f"{COMFY_URL}/upload/image", files=files)
                if res.status_code != 200:
                    raise HTTPException(status_code=500, detail="Failed to upload image to ComfyUI backend")
                upload_data = res.json()
                uploaded_image_name = upload_data.get("name")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Could not connect to ComfyUI server for upload. Is it running on the correct port?")
            
    # 2. Map variables into the workflow
    if prompt and mapping.get("prompt"):
        p_map = mapping["prompt"]
        workflow[p_map["nodeId"]]["inputs"][p_map["field"]] = prompt
        
    if uploaded_image_name and mapping.get("image"):
        i_map = mapping["image"]
        workflow[i_map["nodeId"]]["inputs"][i_map["field"]] = uploaded_image_name
        
    if aspect_ratio and mapping.get("width") and mapping.get("height"):
        current_config = get_current_config()
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
            res = await client.post(f"{COMFY_URL}/prompt", json=payload)
            if res.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to queue generation in ComfyUI")
            data = res.json()
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail=f"Could not connect to ComfyUI server at {COMFY_URL}. Is it running?")
        
    # Log successful generation request
    log_usage(client_ip, tool_id, prompt)
    
    return {"prompt_id": data.get("prompt_id"), "client_id": client_id}


async def status_generator(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
    """
    Generator yielding SSE messages. Uses Websockets for precise progress mapping
    and regular HTTP polling for Queue assignment.
    """
    q = asyncio.Queue()

    node_map = {}
    if tool_id:
        tool = get_tool_settings(tool_id)
        if tool and tool.get("workflowFile"):
            try:
                wf = get_base_workflow(tool["workflowFile"])
                for nid, ndata in wf.items():
                    if isinstance(ndata, dict):
                        node_map[str(nid)] = ndata.get("class_type", "")
            except Exception:
                pass

    FRIENDLY_NAMES = {
        "CheckpointLoaderSimple": "Loading AI Models...",
        "UNETLoader": "Loading AI Models...",
        "LoraLoader": "Loading AI Models...",
        "CLIPTextEncode": "Understanding your prompt...",
        "KSampler": "Generating Image...",
        "KSamplerAdvanced": "Generating Image...",
        "SamplerCustom": "Generating Image...",
        "VAEEncode": "Finalizing Image...",
        "VAEDecode": "Finalizing Image...",
        "ImageScale": "Increasing resolution...",
        "ImageScaleBy": "Increasing resolution...",
        "ImageUpscaleWithModel": "Increasing resolution...",
        "LatentUpscale": "Increasing resolution...",
        "LatentUpscaleBy": "Increasing resolution...",
        "FaceDetailer": "Enhancing faces...",
        "Reactor": "Enhancing faces...",
        "SaveImage": "Wrapping up..."
    }

    # Immediate history check
    async with httpx.AsyncClient() as client:
        try:
            hist_res = await client.get(f"{COMFY_URL}/history/{prompt_id}")
            if hist_res.status_code == 200 and prompt_id in hist_res.json():
                yield json.dumps({"status": "completed"})
                return
        except Exception:
            pass

    async def poll_queue():
        async with httpx.AsyncClient() as client:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    queue_res = await client.get(f"{COMFY_URL}/queue")
                    if queue_res.status_code == 200:
                        queue_data = queue_res.json()
                        pending = queue_data.get("queue_pending", [])
                        for index, p in enumerate(pending):
                            if p[1] == prompt_id:
                                await q.put({"status": "queue", "position": index + 1})
                except Exception:
                    pass
                await asyncio.sleep(2)
                
    async def listen_ws():
        ws_url = COMFY_URL.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"
        try:
            async with websockets.connect(ws_url) as websocket:
                while True:
                    if await request.is_disconnected():
                        break
                    msg = await websocket.recv()
                    if isinstance(msg, bytes):
                        # Binary message: likely a preview image.
                        # ComfyUI prepends an 8-byte header to its binary messages.
                        image_data = msg[8:]
                        b64_img = base64.b64encode(image_data).decode('utf-8')
                        await q.put({"status": "preview", "image": b64_img})
                    elif isinstance(msg, str):
                        data = json.loads(msg)
                        t = data.get("type")
                        if t == "executing":
                            node_id = data.get("data", {}).get("node")
                            if node_id is None:
                                await q.put({"status": "completed"})
                                break
                            else:
                                c_type = node_map.get(str(node_id))
                                friendly = FRIENDLY_NAMES.get(c_type)
                                if friendly:
                                    await q.put({"status": "executing", "message": friendly})
                        elif t == "progress":
                            val = data["data"]["value"]
                            m = data["data"]["max"]
                            await q.put({"status": "progress", "value": val, "max": m})
                        elif t == "execution_start":
                            await q.put({"status": "generating"})
        except Exception as e:
            await q.put({"status": "error", "detail": "Lost WebSocket connection to processing server."})

    task1 = asyncio.create_task(poll_queue())
    task2 = asyncio.create_task(listen_ws())
    
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=1.0)
                yield json.dumps(msg)
                if msg["status"] in ["completed", "error"]:
                    break
            except asyncio.TimeoutError:
                pass
    finally:
        task1.cancel()
        task2.cancel()


@app.get("/api/status")
async def get_status(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
    return EventSourceResponse(status_generator(request, prompt_id, client_id, tool_id))


@app.get("/api/image")
async def get_image(prompt_id: str):
    async with httpx.AsyncClient() as client:
        hist_res = await client.get(f"{COMFY_URL}/history/{prompt_id}")
        if hist_res.status_code != 200:
            raise HTTPException(status_code=404, detail="History not found")
            
        hist_data = hist_res.json()
        if prompt_id not in hist_data:
            raise HTTPException(status_code=404, detail="Prompt ID not generated yet or failed")

        outputs = hist_data[prompt_id].get("outputs", {})
        
        file_info = None
        for node_id, output_data in outputs.items():
            images = output_data.get("images", [])
            if images:
                file_info = images[0]
                break
                
        if not file_info:
            raise HTTPException(status_code=404, detail="No output image found for prompt")
            
        view_url = f"{COMFY_URL}/view?filename={file_info['filename']}&subfolder={file_info.get('subfolder', '')}&type={file_info.get('type', 'output')}"
        img_res = await client.get(view_url)
        if img_res.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch image from ComfyUI backend")
            
        raw_bytes = img_res.content
        clean_bytes = strip_metadata(raw_bytes)
        
        return StreamingResponse(io.BytesIO(clean_bytes), media_type="image/png")

@app.get("/admin")
def serve_admin():
    with open("static/admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/admin/usage")
def get_admin_usage(key: str = None, period: str = "all"):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid admin key")
    
    date_filter = ""
    if period == "weekly":
        date_filter = "WHERE timestamp >= datetime('now', '-7 days')"
    elif period == "monthly":
        date_filter = "WHERE timestamp >= datetime('now', '-1 month')"
    elif period == "quarterly":
        date_filter = "WHERE timestamp >= datetime('now', '-3 months')"
    elif period == "yearly":
        date_filter = "WHERE timestamp >= datetime('now', '-1 year')"

    try:
        conn = sqlite3.connect("usage_logs.db")
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(f"SELECT * FROM usage {date_filter} ORDER BY timestamp DESC LIMIT 500")
        rows = c.fetchall()
        
        # Summary stats
        c.execute(f"SELECT tool_id, COUNT(*) as count FROM usage {date_filter} GROUP BY tool_id")
        tools_summary = [dict(row) for row in c.fetchall()]
        
        c.execute(f"SELECT client_ip, COUNT(*) as count FROM usage {date_filter} GROUP BY client_ip")
        ip_summary = [dict(row) for row in c.fetchall()]
        
        conn.close()
        
        return {
            "logs": [dict(row) for row in rows],
            "tools_summary": tools_summary,
            "ip_summary": ip_summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/admin/config")
def get_admin_config(key: str = None):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return current_config

@app.post("/api/admin/config")
async def update_admin_config(request: Request, key: str = None):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        new_config = await request.json()
        save_config(new_config)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/admin/workflows")
def list_admin_workflows(key: str = None):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    workflows_dir = os.path.join(os.path.dirname(__file__), "workflows")
    files = [f for f in os.listdir(workflows_dir) if f.endswith(".json") and f != "workflows-config.json"]
    return {"files": files}

@app.get("/api/admin/workflows/{filename}")
def get_admin_workflow(filename: str, key: str = None):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    safe_name = os.path.basename(filename)
    path = os.path.join(os.path.dirname(__file__), "workflows", safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.delete("/api/admin/workflows/{filename}")
def delete_admin_workflow(filename: str, key: str = None):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    safe_name = os.path.basename(filename)
    if safe_name == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Cannot delete config")
        
    path = os.path.join(os.path.dirname(__file__), "workflows", safe_name)
    if os.path.exists(path):
        os.remove(path)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/admin/workflows/upload")
async def upload_admin_workflow(file: UploadFile = File(...), key: str = Form(...)):
    current_config = get_current_config()
    expected_key = current_config.get("adminKey", "orangeadmin")
    if key != expected_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Only .json files are allowed")
        
    safe_name = os.path.basename(file.filename)
    if safe_name == "workflows-config.json":
        raise HTTPException(status_code=400, detail="Cannot overwrite config file")
        
    path = os.path.join(os.path.dirname(__file__), "workflows", safe_name)
    content = await file.read()
    try:
        json.loads(content)
        with open(path, "wb") as f:
            f.write(content)
        return {"status": "success", "filename": safe_name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")
