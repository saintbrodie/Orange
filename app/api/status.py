import asyncio
import base64
import json

import httpx
import websockets
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_base_workflow, get_comfy_servers, get_tool_settings
from app.core.database import get_backend_for_prompt

router = APIRouter()


def get_comfy_url():
    """Fallback: returns the highest-priority configured server URL."""
    servers = get_comfy_servers()
    return servers[0].get("url") if servers else "http://127.0.0.1:8188"


@router.get("/api/health")
async def get_health():
    servers = get_comfy_servers()
    if not servers:
        return JSONResponse(status_code=503, content={"status": "offline"})

    async def check_server(url: str):
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(f"{url}/system_stats")
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
        return {"status": "offline", "vram_warning": False}

    results = await asyncio.gather(*(check_server(s.get("url")) for s in servers))
    any_ready = any(r["status"] == "ready" for r in results)
    any_vram_warning = any(r["vram_warning"] for r in results)

    if any_ready:
        return {"status": "ready", "vram_warning": any_vram_warning}
    return JSONResponse(status_code=503, content={"status": "offline"})


async def status_generator(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
    queue = asyncio.Queue()

    node_map = {}
    if tool_id:
        tool = get_tool_settings(tool_id)
        if tool and tool.get("workflowFile"):
            try:
                workflow = get_base_workflow(tool["workflowFile"])
                for node_id, node_data in workflow.items():
                    if isinstance(node_data, dict):
                        node_map[str(node_id)] = node_data.get("class_type", "")
            except Exception:
                pass

    friendly_names = {
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

    target_url = get_backend_for_prompt(prompt_id) or get_comfy_url()

    async def history_has_prompt(client):
        try:
            response = await client.get(f"{target_url}/history/{prompt_id}")
            return response.status_code == 200 and prompt_id in response.json()
        except Exception:
            return False

    async with httpx.AsyncClient(timeout=5.0) as client:
        if await history_has_prompt(client):
            yield json.dumps({"status": "completed"})
            return

    async def poll_queue_and_history():
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    queue_res = await client.get(f"{target_url}/queue")
                    if queue_res.status_code == 200:
                        queue_data = queue_res.json()
                        pending = queue_data.get("queue_pending", [])
                        for index, pending_item in enumerate(pending):
                            if pending_item[1] == prompt_id:
                                await queue.put({"status": "queue", "position": index + 1})
                                break

                    if await history_has_prompt(client):
                        await queue.put({"status": "completed"})
                        return
                except Exception:
                    pass
                await asyncio.sleep(2)

    async def listen_ws():
        ws_url = target_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={client_id}"
        try:
            async with websockets.connect(ws_url) as websocket:
                while True:
                    if await request.is_disconnected():
                        return
                    msg = await websocket.recv()
                    if isinstance(msg, bytes):
                        image_data = msg[8:]
                        await queue.put({"status": "preview", "image": base64.b64encode(image_data).decode("utf-8")})
                        continue

                    data = json.loads(msg)
                    event_type = data.get("type")
                    event_data = data.get("data", {})

                    if event_type == "executing":
                        node_id = event_data.get("node")
                        if node_id is None:
                            await queue.put({"status": "completed"})
                            return
                        class_type = node_map.get(str(node_id))
                        friendly = friendly_names.get(class_type)
                        if friendly:
                            await queue.put({"status": "executing", "message": friendly})
                    elif event_type == "progress":
                        await queue.put(
                            {
                                "status": "progress",
                                "value": event_data.get("value", 0),
                                "max": event_data.get("max", 1),
                            }
                        )
                    elif event_type == "execution_start":
                        await queue.put({"status": "generating"})
        except asyncio.CancelledError:
            raise
        except Exception:
            # Do not immediately mark the job failed. The polling task continues
            # checking queue/history and can still observe successful completion.
            await queue.put({"status": "connection_lost"})

    poll_task = asyncio.create_task(poll_queue_and_history())
    ws_task = asyncio.create_task(listen_ws())

    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                # connection_lost is intentionally internal; polling continues.
                if msg.get("status") == "connection_lost":
                    continue
                yield json.dumps(msg)
                if msg.get("status") in ["completed", "error"]:
                    break
            except asyncio.TimeoutError:
                pass
    finally:
        poll_task.cancel()
        ws_task.cancel()
        await asyncio.gather(poll_task, ws_task, return_exceptions=True)


@router.get("/api/status")
async def get_status(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
    return EventSourceResponse(status_generator(request, prompt_id, client_id, tool_id))
