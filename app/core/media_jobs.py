"""Durable local media jobs. Workers never depend on an open SSE connection."""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

import httpx
from PIL import Image

from app.core.config import PROJECT_ROOT
from app.core import database as db
from app.core.media_providers import ADAPTERS, ProviderError, ProviderResult
from app.core.media_provider_config import credential
from app.core.utils import metadata_scrubbing_enabled
from app.core.terminal_events import emit_terminal_event

OUTPUT_DIR = Path(PROJECT_ROOT) / "runtime" / "media"
TERMINAL = {"completed", "failed", "timed_out", "interrupted"}
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_JOBS = 32


def get_job(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"api-[0-9a-f]{32}", job_id):
        return None
    with db._connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM media_jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def _update(job_id, status, *, remote_id=None, outputs=None, error=None, usage=None):
    with db._connect() as conn:
        conn.execute("UPDATE media_jobs SET status=?, updated=?, remote_id=COALESCE(?,remote_id), outputs=COALESCE(?,outputs), error=? WHERE id=?",
                     (status, time.time(), remote_id, json.dumps(outputs) if outputs is not None else None, error, job_id))
        conn.execute("UPDATE usage SET status=?, error=?, usage_json=COALESCE(?,usage_json) WHERE prompt_id=?",
                     (status, error, json.dumps(usage) if usage is not None else None, job_id))
    labels = {"running": "Generating", "scrubbing": "Removing metadata", "completed": "Generation complete", "failed": "Generation failed", "timed_out": "Generation timed out", "interrupted": "Generation interrupted"}
    if status in labels:
        job = get_job(job_id)
        emit_terminal_event("api_generation", "complete" if status == "completed" else "failed" if status in TERMINAL else "working", f"{job['provider']}: {labels[status]}")


def output_path(filename):
    if not isinstance(filename, str) or not re.fullmatch(r"api-[0-9a-f]{32}-[0-9]+\.(png|jpeg|webp|gif|mp4)", filename):
        raise ValueError("Invalid local output filename.")
    root = OUTPUT_DIR.resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root:
        raise ValueError("Invalid local output path.")
    return candidate


def _scrub_mp4(data):
    """Blank metadata boxes in place, preserving all media/chunk offsets."""
    result = bytearray(data)
    def visit(start, end):
        offset = start
        while offset + 8 <= end:
            size = int.from_bytes(result[offset:offset+4], "big")
            kind = bytes(result[offset+4:offset+8])
            header = 8
            if size == 1:
                if offset + 16 > end: raise ProviderError("Invalid video container.")
                size = int.from_bytes(result[offset+8:offset+16], "big"); header = 16
            if size == 0: size = end - offset
            if size < header or offset + size > end: raise ProviderError("Invalid video container.")
            if kind in {b"udta", b"meta"}:
                result[offset+4:offset+8] = b"free"
                result[offset+header:offset+size] = bytes(size-header)
            elif kind in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
                visit(offset+header, offset+size)
            offset += size
    visit(0, len(result))
    return bytes(result)


def _store_outputs(job_id, media, output_type, scrub=True):
    if not media or len(media) > 8:
        raise ProviderError("Provider returned an invalid number of outputs.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    outputs, written = [], []
    try:
        for index, item in enumerate(media):
            data = item.data
            if not data or len(data) > MAX_OUTPUT_BYTES:
                raise ProviderError("Provider output exceeds Orange's local media limit.")
            if output_type == "image":
                # Re-encode raster pixels so EXIF, prompts and other metadata never
                # enter local user-facing media. No SVG or arbitrary HTML output.
                with Image.open(BytesIO(data)) as image:
                    if image.width * image.height > 40_000_000:
                        raise ProviderError("Provider returned an oversized image.")
                    image.load()
                    original_format = image.format
                    clean = Image.new("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB", image.size)
                    clean.paste(image)
                    buffer = BytesIO()
                    clean.save(buffer, "PNG")
                    if scrub:
                        data = buffer.getvalue()
                extension, mime = "png", "image/png"
                if not scrub:
                    extension, mime = {"PNG": ("png", "image/png"), "JPEG": ("jpeg", "image/jpeg"), "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif")}.get(original_format, ("png", "image/png"))
            else:
                if len(data) < 12 or data[4:8] != b"ftyp":
                    raise ProviderError("Provider returned invalid MP4 video.")
                extension, mime = "mp4", "video/mp4"
                if scrub:
                    data = _scrub_mp4(data)
            filename = f"{job_id}-{index}.{extension}"
            destination = output_path(filename)
            temporary = destination.with_suffix(".part")
            written.extend([temporary, destination])
            temporary.write_bytes(data)
            temporary.replace(destination)
            outputs.append({"index": index, "filename": filename, "type": "output", "subfolder": "", "media_type": mime})
        return outputs
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise


def list_completed():
    try:
        with db._connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT j.id AS prompt_id, j.output_type AS type, j.outputs, u.* FROM media_jobs j LEFT JOIN usage u ON u.prompt_id=j.id WHERE j.status='completed' ORDER BY j.created DESC")]
    except (OSError, sqlite3.OperationalError):
        return []


def queue_position(job):
    with db._connect() as conn:
        return max(1, conn.execute("SELECT COUNT(*) FROM media_jobs WHERE status='queued' AND created<=?", (job["created"],)).fetchone()[0])


def delete_job(job_id):
    job = get_job(job_id)
    if not job:
        return False
    if job["status"] not in TERMINAL:
        raise ValueError("Wait for this generation to finish before deleting it.")
    for item in json.loads(job["outputs"]):
        output_path(item["filename"]).unlink(missing_ok=True)
    with db._connect() as conn:
        conn.execute("DELETE FROM media_jobs WHERE id=?", (job_id,))
        conn.execute("DELETE FROM usage WHERE prompt_id=?", (job_id,))
    return True


class MediaJobManager:
    def __init__(self):
        self.tasks = {}
        self.slots = None

    def _schedule(self, job_id, request=None):
        if self.slots is None:
            self.slots = asyncio.Semaphore(2)
        task = asyncio.create_task(self._run(job_id, request))
        self.tasks[job_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(job_id, None))

    async def start(self):
        self.slots = asyncio.Semaphore(2)
        with db._connect() as conn:
            conn.row_factory = sqlite3.Row
            pending = [dict(row) for row in conn.execute("SELECT * FROM media_jobs WHERE status NOT IN ('completed','failed','timed_out','interrupted')")]
        for job in pending:
            if job["remote_id"] and getattr(ADAPTERS.get(job["provider"]), "resumable", False):
                self._schedule(job["id"])
            else:
                _update(job["id"], "interrupted", error="Orange restarted before this job finished. The provider may have accepted the request; check provider usage before trying again.")

    async def stop(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()

    def submit(self, provider, model, tool_id, request, client_ip):
        if len(self.tasks) >= MAX_JOBS:
            raise ProviderError("Orange's API generation queue is full. Try again later.")
        job_id = f"api-{uuid.uuid4().hex}"
        now = time.time()
        timeout = 1800 if model.output == "video" else 900
        # Job and usage reservation are one transaction. user_id is deliberately
        # nullable until Orange has authenticated end-user identities/budgets.
        with db._connect() as conn:
            conn.execute("INSERT INTO media_jobs (id,provider,model,output_type,status,created,updated,timeout) VALUES (?,?,?,?,?,?,?,?)",
                         (job_id, provider, model.id, model.output, "queued", now, now, timeout))
            conn.execute("INSERT INTO usage (client_ip,tool_id,prompt,prompt_id,status,provider,model) VALUES (?,?,?,?,?,?,?)",
                         (client_ip, tool_id, request.prompt, job_id, "queued", provider, model.id))
        self._schedule(job_id, request)
        return {"prompt_id": job_id, "client_id": job_id, "provider": provider}

    async def _run(self, job_id, request):
        job = get_job(job_id)
        try:
            remaining = job["created"] + job["timeout"] - time.time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            await asyncio.wait_for(self._execute(job, request), timeout=remaining)
        except asyncio.CancelledError:
            # Persist remote handles, allowing safe GET-only recovery at startup.
            raise
        except asyncio.TimeoutError:
            _update(job_id, "timed_out", error="Generation timed out. The provider may still finish or charge for this request; check provider usage before trying again.")
        except ProviderError as exc:
            _update(job_id, "failed", error=str(exc))
        except Exception:
            # Exceptions can contain headers, keys or complete response bodies.
            _update(job_id, "failed", error="Orange could not process this generation. Check provider usage before trying again.")

    async def _execute(self, job, request):
        async with self.slots:
            adapter = ADAPTERS[job["provider"]]
            key = credential(job["provider"])
            if not key:
                raise ProviderError("Provider credential is unavailable. Configure it in Admin.")
            _update(job["id"], "running")
            async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=15), follow_redirects=False) as client:
                result = ProviderResult(remote_id=job["remote_id"]) if job["remote_id"] else await adapter.submit(client, key, request)
                if result.remote_id:
                    _update(job["id"], "processing", remote_id=result.remote_id, usage=result.usage)
                while not result.media and result.remote_id:
                    await asyncio.sleep(5)
                    result = await adapter.poll(client, key, result.remote_id)
                _update(job["id"], "downloading")
                scrub = metadata_scrubbing_enabled()
                if scrub:
                    _update(job["id"], "scrubbing")
                outputs = _store_outputs(job["id"], result.media, job["output_type"], scrub=scrub)
                _update(job["id"], "completed", outputs=outputs, usage=result.usage or None)


job_manager = MediaJobManager()


async def status_events(request, job_id):
    while not await request.is_disconnected():
        job = get_job(job_id)
        if not job:
            yield json.dumps({"status": "error", "detail": "Generation was not found."})
            return
        state = job["status"]
        event = {"status": "queue", "position": queue_position(job)} if state == "queued" else {"status": "executing", "message": "Generating..."}
        if state in TERMINAL:
            event = {"status": "completed"} if state == "completed" else {"status": "error", "detail": job["error"] or "Generation failed."}
        elif state == "scrubbing":
            event = {"status": "executing", "message": "Removing metadata…"}
        elif state in {"processing", "downloading"}:
            event = {"status": "executing", "message": "Generating…" if state == "processing" else "Saving media locally…"}
        yield json.dumps(event)
        if state in TERMINAL:
            return
        await asyncio.sleep(1)
