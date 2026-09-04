import asyncio
import base64
import json
import os
import time
from urllib.parse import urlencode, urlparse, urlunparse

import websockets
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.core.backends import get_backend_client
from app.core.config import get_base_workflow, get_comfy_servers, get_tool_settings
from app.core.database import get_backend_for_prompt, update_usage_status

router = APIRouter()

JOB_STATUS_TIMEOUT_SECONDS = max(60, int(os.environ.get("ORANGE_JOB_STATUS_TIMEOUT_SECONDS", "7200")))


def get_comfy_url():
    """Fallback: returns the highest-priority configured server URL."""
    servers = get_comfy_servers()
    return servers[0].get("url") if servers else "http://127.0.0.1:8188"


def _websocket_url(target_url: str, client_id: str) -> str:
    parsed = urlparse(target_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}/ws" if base_path else "/ws"
    return urlunparse((scheme, parsed.netloc, path, "", urlencode({"clientId": client_id}), ""))


def _technical_execution_error(event_data: dict) -> str:
    details = {
        "node_id": event_data.get("node_id"),
        "node_type": event_data.get("node_type"),
        "exception_type": event_data.get("exception_type"),
        "exception_message": event_data.get("exception_message"),
        "traceback": event_data.get("traceback"),
    }
    return json.dumps({key: value for key, value in details.items() if value}, ensure_ascii=False, default=str)[:8000]


def _history_record_state(record: dict):
    """Return (state, technical_error) for a ComfyUI history record."""
    if not isinstance(record, dict):
        return None, None

    status = record.get("status") if isinstance(record.get("status"), dict) else {}
    messages = status.get("messages", []) if isinstance(status, dict) else []

    if isinstance(messages, list):
        for item in reversed(messages):
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            event_type = item[0]
            event_data = item[1] if isinstance(item[1], dict) else {}
            if event_type == "execution_error":
                return "error", _technical_execution_error(event_data)
            if event_type == "execution_interrupted":
                return "interrupted", json.dumps(event_data, ensure_ascii=False, default=str)[:8000]

    if status.get("status_str") == "error":
        return "error", json.dumps(status, ensure_ascii=False, default=str)[:8000]
    if status.get("completed") is True:
        return "completed", None
    if record.get("outputs"):
        return "completed", None
    return None, None


def _record_failure(prompt_id: str, target_url: str, status: str, technical_error: str) -> None:
    technical_error = technical_error or "No technical details were provided by ComfyUI."
    print(f"ComfyUI job {prompt_id} on {target_url} ended with {status}: {technical_error}")
    update_usage_status(prompt_id, status, technical_error)


@router.get("/api/health")
async def get_health():
    servers = get_comfy_servers()
    if not servers:
        return JSONResponse(status_code=503, content={"status": "offline"})

    client = await get_backend_client()

    async def check_server(url: str):
        try:
            res = await client.get(f"{str(url).rstrip('/')}/system_stats", timeout=2.0)
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
    any_ready = any(result["status"] == "ready" for result in results)
    any_vram_warning = any(result["vram_warning"] for result in results)

    if any_ready:
        return {"status": "ready", "vram_warning": any_vram_warning}
    return JSONResponse(status_code=503, content={"status": "offline"})


async def status_generator(request: Request, prompt_id: str, client_id: str, tool_id: str = None):
    queue = asyncio.Queue()
    monitoring_started = time.monotonic()

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

    target_url = (get_backend_for_prompt(prompt_id) or get_comfy_url()).rstrip("/")
    client = await get_backend_client()

    async def get_history_state():
        try:
            response = await client.get(f"{target_url}/history/{prompt_id}", timeout=5.0)
            if response.status_code != 200:
                return None, None
            payload = response.json()
            record = payload.get(prompt_id) if isinstance(payload, dict) else None
            return _history_record_state(record)
        except Exception:
            return None, None

    initial_state, initial_error = await get_history_state()
    if initial_state == "completed":
        update_usage_status(prompt_id, "completed")
        yield json.dumps({"status": "completed"})
        return
    if initial_state in {"error", "interrupted"}:
        _record_failure(prompt_id, target_url, initial_state, initial_error)
        detail = "Generation was interrupted." if initial_state == "interrupted" else "Generation failed in the processing workflow."
        yield json.dumps({"status": "error", "detail": detail})
        return

    async def poll_queue_and_history():
        while True:
            if await request.is_disconnected():
                return
            try:
                queue_res = await client.get(f"{target_url}/queue", timeout=5.0)
                if queue_res.status_code == 200:
                    queue_data = queue_res.json()
                    pending = queue_data.get("queue_pending", [])
                    running = queue_data.get("queue_running", [])

                    found_running = False
                    if isinstance(running, list):
                        for running_item in running:
                            if isinstance(running_item, (list, tuple)) and len(running_item) > 1 and running_item[1] == prompt_id:
                                found_running = True
                                update_usage_status(prompt_id, "running")
                                await queue.put({"status": "generating"})
                                break

                    if not found_running and isinstance(pending, list):
                        for index, pending_item in enumerate(pending):
                            if isinstance(pending_item, (list, tuple)) and len(pending_item) > 1 and pending_item[1] == prompt_id:
                                update_usage_status(prompt_id, "queued")
                                await queue.put({"status": "queue", "position": index + 1})
                                break

                history_state, technical_error = await get_history_state()
                if history_state == "completed":
                    update_usage_status(prompt_id, "completed")
                    await queue.put({"status": "completed"})
                    return
                if history_state in {"error", "interrupted"}:
                    _record_failure(prompt_id, target_url, history_state, technical_error)
                    detail = "Generation was interrupted." if history_state == "interrupted" else "Generation failed in the processing workflow."
                    await queue.put({"status": "error", "detail": detail})
                    return
            except Exception:
                pass
            await asyncio.sleep(2)

    async def listen_ws():
        ws_url = _websocket_url(target_url, client_id)
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
                    event_prompt_id = event_data.get("prompt_id") if isinstance(event_data, dict) else None
                    if event_prompt_id and event_prompt_id != prompt_id:
                        continue

                    if event_type == "executing":
                        node_id = event_data.get("node")
                        if node_id is None:
                            update_usage_status(prompt_id, "completed")
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
                        update_usage_status(prompt_id, "running")
                        await queue.put({"status": "generating"})
                    elif event_type == "execution_error":
                        technical_error = _technical_execution_error(event_data)
                        _record_failure(prompt_id, target_url, "error", technical_error)
                        await queue.put({"status": "error", "detail": "Generation failed in the processing workflow."})
                        return
                    elif event_type == "execution_interrupted":
                        technical_error = json.dumps(event_data, ensure_ascii=False, default=str)[:8000]
                        _record_failure(prompt_id, target_url, "interrupted", technical_error)
                        await queue.put({"status": "error", "detail": "Generation was interrupted."})
                        return
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
            if time.monotonic() - monitoring_started >= JOB_STATUS_TIMEOUT_SECONDS:
                technical_error = f"Orange status monitoring exceeded {JOB_STATUS_TIMEOUT_SECONDS} seconds."
                _record_failure(prompt_id, target_url, "monitor_timeout", technical_error)
                yield json.dumps(
                    {
                        "status": "error",
                        "detail": "Generation monitoring timed out. The backend may still be working; check the admin dashboard.",
                    }
                )
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
