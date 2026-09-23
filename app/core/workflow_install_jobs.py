import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from app.core.config import PROJECT_ROOT

JOBS_DIR = os.path.join(PROJECT_ROOT, "workflows", ".runtime")
JOBS_PATH = os.path.join(JOBS_DIR, "workflow-install-jobs.json")
MAX_JOBS = 50
_ACTIVE_STATES = {"queued", "running"}
_TERMINAL_STATES = {"completed", "failed", "interrupted", "canceled"}
_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_loaded = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_server(url: str) -> str:
    return str(url or "").strip().rstrip("/")


def _persist_locked() -> None:
    os.makedirs(JOBS_DIR, exist_ok=True)
    ordered = sorted(_jobs.values(), key=lambda item: item.get("createdAt", ""), reverse=True)[:MAX_JOBS]
    payload = {"schemaVersion": 1, "jobs": ordered}
    tmp = JOBS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, JOBS_PATH)


def _ensure_loaded() -> None:
    global _loaded, _jobs
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            with open(JOBS_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            loaded = payload.get("jobs") if isinstance(payload, dict) else []
            if isinstance(loaded, list):
                _jobs = {
                    str(item.get("id")): dict(item)
                    for item in loaded
                    if isinstance(item, dict) and item.get("id")
                }
        except (OSError, ValueError):
            _jobs = {}

        interrupted = False
        for job in _jobs.values():
            if job.get("state") in _ACTIVE_STATES:
                job["state"] = "interrupted"
                job["stage"] = "interrupted"
                job["cancelRequested"] = False
                job["error"] = "Orange restarted while this install was running. Retry the install to continue."
                job["finishedAt"] = _now()
                job["updatedAt"] = job["finishedAt"]
                interrupted = True
        if interrupted:
            _persist_locked()


def create_job(pack_id: str, server_url: str, models_root: str | None = None) -> tuple[dict, bool]:
    _ensure_loaded()
    server_url = _normalize_server(server_url)
    models_root = str(models_root or "").strip() or None
    with _lock:
        for job in _jobs.values():
            if (
                job.get("state") in _ACTIVE_STATES
                and job.get("packId") == pack_id
                and _normalize_server(job.get("serverUrl")) == server_url
            ):
                return deepcopy(job), False

        job_id = uuid.uuid4().hex
        created = _now()
        job = {
            "id": job_id,
            "packId": pack_id,
            "serverUrl": server_url,
            "modelsRoot": models_root,
            "state": "queued",
            "stage": "queued",
            "mode": None,
            "message": "Waiting to start…",
            "error": None,
            "downloadPlan": [],
            "downloadFileCount": 0,
            "downloadBytesTotal": 0,
            "downloadBytesKnown": 0,
            "downloadSizeComplete": False,
            "diskSpace": None,
            "files": [],
            "result": None,
            "cancelRequested": False,
            "createdAt": created,
            "startedAt": None,
            "updatedAt": created,
            "finishedAt": None,
        }
        _jobs[job_id] = job
        _persist_locked()
        return deepcopy(job), True


def retry_job(job_id: str) -> tuple[dict, bool]:
    old = get_job(job_id)
    if not old:
        raise KeyError(job_id)
    if old.get("state") in _ACTIVE_STATES:
        return old, False
    return create_job(old.get("packId", ""), old.get("serverUrl", ""), old.get("modelsRoot"))


def get_job(job_id: str) -> dict | None:
    _ensure_loaded()
    with _lock:
        job = _jobs.get(job_id)
        return deepcopy(job) if job else None


def list_jobs(server_url: str | None = None, limit: int = 50) -> list[dict]:
    _ensure_loaded()
    normalized = _normalize_server(server_url) if server_url else None
    with _lock:
        jobs = list(_jobs.values())
        if normalized:
            jobs = [item for item in jobs if _normalize_server(item.get("serverUrl")) == normalized]
        jobs.sort(key=lambda item: item.get("createdAt", ""), reverse=True)
        return deepcopy(jobs[: max(1, min(int(limit or 50), MAX_JOBS))])


def clear_jobs(server_url: str | None = None) -> int:
    """Remove terminal job history while preserving anything still active."""
    _ensure_loaded()
    normalized = _normalize_server(server_url) if server_url else None
    with _lock:
        removable = [
            job_id
            for job_id, job in _jobs.items()
            if job.get("state") in _TERMINAL_STATES
            and (not normalized or _normalize_server(job.get("serverUrl")) == normalized)
        ]
        for job_id in removable:
            _jobs.pop(job_id, None)
        if removable:
            _persist_locked()
        return len(removable)


def update_job(job_id: str, **changes) -> dict:
    _ensure_loaded()
    with _lock:
        if job_id not in _jobs:
            raise KeyError(job_id)
        job = _jobs[job_id]
        for key, value in changes.items():
            job[key] = deepcopy(value)
        job["updatedAt"] = _now()
        _persist_locked()
        return deepcopy(job)


def mark_running(job_id: str, stage: str = "inspecting", message: str = "Inspecting ComfyUI…") -> dict:
    return update_job(job_id, state="running", stage=stage, message=message, startedAt=_now(), error=None)


def request_cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if job.get("state") not in _ACTIVE_STATES:
        return job
    return update_job(
        job_id,
        cancelRequested=True,
        stage="canceling",
        message="Canceling workflow setup…",
    )


def is_cancel_requested(job_id: str) -> bool:
    job = get_job(job_id)
    return bool(job and job.get("cancelRequested"))


def cancel_job(job_id: str, message: str = "Workflow setup canceled.") -> dict:
    finished = _now()
    return update_job(
        job_id,
        state="canceled",
        stage="canceled",
        message=message,
        error=None,
        cancelRequested=False,
        finishedAt=finished,
    )


def set_download_plan(job_id: str, plan: list[dict]) -> dict:
    files = []
    for index, item in enumerate(plan or []):
        file = dict(item) if isinstance(item, dict) else {}
        known_total = file.get("bytesTotal")
        file.update(
            {
                "index": index,
                "state": "pending",
                "bytesDownloaded": 0,
                "bytesTotal": int(known_total) if isinstance(known_total, (int, float)) and known_total >= 0 else None,
                "speedBps": 0,
            }
        )
        files.append(file)
    return update_job(job_id, downloadPlan=plan or [], files=files)


def update_file_progress(
    job_id: str,
    filename: str,
    *,
    state: str | None = None,
    bytes_downloaded: int | None = None,
    bytes_total: int | None = None,
    speed_bps: float | None = None,
    destination: str | None = None,
    error: str | None = None,
) -> dict:
    _ensure_loaded()
    with _lock:
        if job_id not in _jobs:
            raise KeyError(job_id)
        job = _jobs[job_id]
        files = job.setdefault("files", [])
        target = next((item for item in files if item.get("filename") == filename), None)
        if target is None:
            target = {"filename": filename, "state": "pending", "bytesDownloaded": 0, "bytesTotal": None, "speedBps": 0}
            files.append(target)
        if state is not None:
            target["state"] = state
        if bytes_downloaded is not None:
            target["bytesDownloaded"] = int(bytes_downloaded)
        if bytes_total is not None:
            target["bytesTotal"] = int(bytes_total)
        if speed_bps is not None:
            target["speedBps"] = float(speed_bps)
        if destination is not None:
            target["destination"] = destination
        if error is not None:
            target["error"] = error
        job["updatedAt"] = _now()
        _persist_locked()
        return deepcopy(job)


def complete_job(job_id: str, result: dict, message: str = "Workflow is ready.") -> dict:
    finished = _now()
    return update_job(
        job_id,
        state="completed",
        stage="completed",
        message=message,
        error=None,
        cancelRequested=False,
        result=result,
        finishedAt=finished,
    )


def fail_job(job_id: str, error: str, stage: str | None = None) -> dict:
    finished = _now()
    changes = {
        "state": "failed",
        "message": "Workflow install failed.",
        "error": str(error),
        "cancelRequested": False,
        "finishedAt": finished,
    }
    if stage:
        changes["stage"] = stage
    return update_job(job_id, **changes)
