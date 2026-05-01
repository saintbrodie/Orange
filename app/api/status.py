import asyncio
import json
import websockets
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_tool_settings, get_base_workflow, load_config

router = APIRouter()

def get_comfy_url():
    return load_config().get("comfyServerUrl", "http://127.0.0.1:8188")

@router.get("/api/health")
async def get_health():
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{get_comfy_url()}/system_stats")
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

async def status_generator(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
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
        "KSampler": "Generating...",
        "KSamplerAdvanced": "Generating...",
        "SamplerCustom": "Generating...",
        "VAEEncode": "Finalizing...",
        "VAEDecode": "Finalizing...",
        "ImageScale": "Increasing resolution...",
        "ImageScaleBy": "Increasing resolution...",
        "ImageUpscaleWithModel": "Increasing resolution...",
        "LatentUpscale": "Increasing resolution...",
        "LatentUpscaleBy": "Increasing resolution...",
        "FaceDetailer": "Enhancing faces...",
        "Reactor": "Enhancing faces...",
        "SaveImage": "Wrapping up...",
        "WanVideoSampler": "Generating Video...",
        "AnimateDiffEvolve": "Generating Video...",
        "AnimateDiffSampler": "Generating Video...",
        "VideoLinearCFGGuidance": "Generating Video...",
        "VHS_VideoCombine": "Encoding Video...",
        "SaveAnimatedWEBP": "Encoding Video...",
        "StableAudioSampler": "Generating Audio...",
        "SaveAudio": "Saving Audio...",
    }

    async with httpx.AsyncClient() as client:
        try:
            hist_res = await client.get(f"{get_comfy_url()}/history/{prompt_id}")
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
                    queue_res = await client.get(f"{get_comfy_url()}/queue")
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
        import base64
        ws_url = get_comfy_url().replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"
        try:
            async with websockets.connect(ws_url) as websocket:
                while True:
                    if await request.is_disconnected():
                        break
                    msg = await websocket.recv()
                    if isinstance(msg, bytes):
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
        except Exception:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    r = await client.get(f"{get_comfy_url()}/history/{prompt_id}")
                    if r.status_code == 200 and prompt_id in r.json():
                        await q.put({"status": "completed"})
                        return
            except Exception:
                pass
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


@router.get("/api/status")
async def get_status(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
    return EventSourceResponse(status_generator(request, prompt_id, client_id, tool_id))
