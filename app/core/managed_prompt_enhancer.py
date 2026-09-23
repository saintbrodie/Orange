import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import PROJECT_ROOT

MANAGED_MODEL_ID = "gemma-4-e2b"
MANAGED_MODEL_NAME = "Gemma 4 E2B Instruct"
MANAGED_MODEL_FILENAME = "gemma-4-E2B_q4_0-it.gguf"
MANAGED_MODEL_BYTES = 3349516256
MANAGED_MODEL_SHA256 = "fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634"
MANAGED_MODEL_REVISION = "347eef722ec7f151f37d1ef0b5c7c77d8de4efcb"
MANAGED_MODEL_URL = (
    "https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/"
    f"{MANAGED_MODEL_REVISION}/{MANAGED_MODEL_FILENAME}?download=true"
)
MANAGED_BASE_URL = "http://127.0.0.1:7071/v1"
MANAGED_HEALTH_URL = "http://127.0.0.1:7071/health"
MANAGED_PORT = 7071
LLAMA_BUILD = "b10964"

RUNTIME_ROOT = os.path.join(PROJECT_ROOT, "workflows", ".runtime", "prompt-enhancer")
RUNTIME_DIR = os.path.join(RUNTIME_ROOT, "llama.cpp")
MODELS_DIR = os.path.join(RUNTIME_ROOT, "models")
DOWNLOADS_DIR = os.path.join(RUNTIME_ROOT, "downloads")
STATE_PATH = os.path.join(RUNTIME_ROOT, "state.json")
MODEL_PATH = os.path.join(MODELS_DIR, MANAGED_MODEL_FILENAME)

_RUNTIME_ASSETS = {
    ("windows", "x86_64"): {
        "name": f"llama-{LLAMA_BUILD}-bin-win-cpu-x64.zip",
        "sha256": "917f39c076402c421224824607397af20f53625a60defc20e8dd22446bf4c5d7",
        "archive": "zip",
    },
    ("windows", "arm64"): {
        "name": f"llama-{LLAMA_BUILD}-bin-win-cpu-arm64.zip",
        "sha256": "4b6a004b076eea47c318bea35cf1db2ff2bf037738b04645646ae8d7c3159478",
        "archive": "zip",
    },
    ("linux", "x86_64"): {
        "name": f"llama-{LLAMA_BUILD}-bin-ubuntu-x64.tar.gz",
        "sha256": "9abf88aea48a55d0f80edb1ee20220b186848cca0b4e919d71518cfd7ca67443",
        "archive": "tar.gz",
    },
    ("linux", "arm64"): {
        "name": f"llama-{LLAMA_BUILD}-bin-ubuntu-arm64.tar.gz",
        "sha256": "5f0e9c95d970892e43380f82ebcab960edfd20a1cd0f7abffa13b29fdb924949",
        "archive": "tar.gz",
    },
    ("darwin", "arm64"): {
        "name": f"llama-{LLAMA_BUILD}-bin-macos-arm64.tar.gz",
        "sha256": "033c845c1df9bf945ff37bb193238b40910b2244be3e1e637b2ceb5878f1a6f5",
        "archive": "tar.gz",
    },
    ("darwin", "x86_64"): {
        "name": f"llama-{LLAMA_BUILD}-bin-macos-x64.tar.gz",
        "sha256": "03430a394d0a169a5e6d8f01c09f48cf58eb026af6fc95940a4a528e2e50cf38",
        "archive": "tar.gz",
    },
}
for _asset in _RUNTIME_ASSETS.values():
    _asset["url"] = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_BUILD}/{_asset['name']}"

_state_lock = threading.RLock()
_process_lock = threading.RLock()
_install_tasks: set[asyncio.Task] = set()
_server_process: subprocess.Popen | None = None
_server_log = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _machine() -> str:
    value = platform.machine().lower()
    if value in {"amd64", "x64", "x86-64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    return value


def runtime_asset() -> dict | None:
    asset = _RUNTIME_ASSETS.get((platform.system().lower(), _machine()))
    return dict(asset) if asset else None


def _read_state() -> dict:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(data: dict) -> dict:
    os.makedirs(RUNTIME_ROOT, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    payload = dict(data)
    payload["updatedAt"] = _now()
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, STATE_PATH)
    return payload


def _update_state(**changes) -> dict:
    with _state_lock:
        state = _read_state()
        state.update(changes)
        return _write_state(state)


def _server_executable() -> str | None:
    names = {"llama-server", "llama-server.exe"}
    if not os.path.isdir(RUNTIME_DIR):
        return None
    for root, _dirs, files in os.walk(RUNTIME_DIR):
        for filename in files:
            if filename.lower() in names:
                return os.path.join(root, filename)
    return None


def _process_running() -> bool:
    with _process_lock:
        return _server_process is not None and _server_process.poll() is None


def get_status() -> dict:
    asset = runtime_asset()
    with _state_lock:
        state = _read_state()
        if state.get("state") in {"queued", "installing"} and not _install_tasks:
            state.update(
                state="interrupted",
                stage="interrupted",
                error="Orange restarted while the prompt enhancer was installing. Retry the install to continue.",
                finishedAt=_now(),
            )
            state = _write_state(state)

    runtime_ok = bool(_server_executable())
    try:
        model_ok = os.path.isfile(MODEL_PATH) and os.path.getsize(MODEL_PATH) == MANAGED_MODEL_BYTES
    except OSError:
        model_ok = False
    installed = runtime_ok and model_ok
    return {
        **state,
        "supported": asset is not None,
        "platform": f"{platform.system()} {_machine()}",
        "installed": installed,
        "runtimeInstalled": runtime_ok,
        "modelInstalled": model_ok,
        "running": _process_running(),
        "baseUrl": MANAGED_BASE_URL,
        "model": {
            "id": MANAGED_MODEL_ID,
            "name": MANAGED_MODEL_NAME,
            "filename": MANAGED_MODEL_FILENAME,
            "quantization": "Q4_0 QAT",
            "bytes": MANAGED_MODEL_BYTES,
            "sha256": MANAGED_MODEL_SHA256,
            "source": "google/gemma-4-E2B-it-qat-q4_0-gguf",
            "revision": MANAGED_MODEL_REVISION,
        },
        "runtime": {
            "name": "llama.cpp",
            "build": LLAMA_BUILD,
            "asset": asset.get("name") if asset else None,
        },
    }


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: str, expected_sha256: str, label: str, expected_bytes: int | None = None) -> None:
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    part = destination + ".part"
    try:
        if os.path.exists(part):
            os.remove(part)
        request = urllib.request.Request(url, headers={"User-Agent": "Orange/1.0"})
        downloaded = 0
        started = time.monotonic()
        last_report = 0.0
        with urllib.request.urlopen(request, timeout=30) as response, open(part, "wb") as output:
            raw_total = response.headers.get("Content-Length")
            try:
                total = int(raw_total) if raw_total else expected_bytes
            except (TypeError, ValueError):
                total = expected_bytes
            _update_state(
                stage="downloading",
                currentFile=label,
                bytesDownloaded=0,
                bytesTotal=total,
                speedBps=0,
                message=f"Downloading {label}…",
            )
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                now = time.monotonic()
                if now - last_report >= 0.75:
                    elapsed = max(now - started, 0.001)
                    _update_state(
                        bytesDownloaded=downloaded,
                        bytesTotal=total,
                        speedBps=downloaded / elapsed,
                    )
                    last_report = now
            output.flush()
            os.fsync(output.fileno())
        os.replace(part, destination)
        _update_state(
            stage="verifying",
            currentFile=label,
            bytesDownloaded=downloaded,
            bytesTotal=expected_bytes or downloaded,
            speedBps=0,
            message=f"Verifying {label}…",
        )
        actual = _sha256(destination)
        if actual.lower() != expected_sha256.lower():
            os.remove(destination)
            raise RuntimeError(f"Checksum verification failed for {label}")
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def _safe_target(base: str, name: str) -> str:
    target = os.path.abspath(os.path.join(base, name))
    root = os.path.abspath(base) + os.sep
    if target != os.path.abspath(base) and not target.startswith(root):
        raise RuntimeError("Runtime archive contains an unsafe path")
    return target


def _extract_runtime(archive_path: str, archive_type: str) -> None:
    staging = RUNTIME_DIR + ".new"
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    try:
        if archive_type == "zip":
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    _safe_target(staging, member.filename)
                archive.extractall(staging)
        else:
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive.getmembers():
                    member_target = _safe_target(staging, member.name)
                    if member.issym():
                        link_target = os.path.abspath(os.path.join(os.path.dirname(member_target), member.linkname))
                        _safe_target(staging, os.path.relpath(link_target, staging))
                    elif member.islnk():
                        _safe_target(staging, member.linkname)
                archive.extractall(staging)
        if os.path.isdir(RUNTIME_DIR):
            shutil.rmtree(RUNTIME_DIR)
        os.replace(staging, RUNTIME_DIR)
        executable = _server_executable()
        if not executable:
            raise RuntimeError("llama-server was not found in the downloaded runtime")
        if os.name != "nt":
            os.chmod(executable, os.stat(executable).st_mode | 0o111)
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)


def _install_sync(job_id: str) -> None:
    asset = runtime_asset()
    if not asset:
        raise RuntimeError(f"Managed prompt enhancement is not packaged for {platform.system()} {_machine()}")
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)

    if not _server_executable():
        runtime_archive = os.path.join(DOWNLOADS_DIR, asset["name"])
        if not os.path.isfile(runtime_archive) or _sha256(runtime_archive) != asset["sha256"]:
            _download(asset["url"], runtime_archive, asset["sha256"], f"llama.cpp {LLAMA_BUILD}")
        _update_state(stage="extracting", message="Installing the local llama.cpp runtime…", currentFile=asset["name"])
        _extract_runtime(runtime_archive, asset["archive"])

    model_valid = False
    if os.path.isfile(MODEL_PATH):
        try:
            model_valid = os.path.getsize(MODEL_PATH) == MANAGED_MODEL_BYTES
        except OSError:
            pass
    if not model_valid:
        _download(
            MANAGED_MODEL_URL,
            MODEL_PATH,
            MANAGED_MODEL_SHA256,
            MANAGED_MODEL_FILENAME,
            MANAGED_MODEL_BYTES,
        )

    _update_state(
        jobId=job_id,
        state="completed",
        stage="ready",
        message="Managed Local is ready.",
        error=None,
        currentFile=None,
        bytesDownloaded=0,
        bytesTotal=None,
        speedBps=0,
        finishedAt=_now(),
    )


async def _run_install(job_id: str) -> None:
    try:
        _update_state(state="installing", stage="preparing", message="Preparing Managed Local…", startedAt=_now(), error=None)
        await asyncio.to_thread(_install_sync, job_id)
    except Exception as exc:
        _update_state(
            state="failed",
            stage="failed",
            message="Managed Local installation failed.",
            error=str(exc),
            finishedAt=_now(),
            speedBps=0,
        )


def schedule_install() -> dict:
    status = get_status()
    if status.get("installed"):
        return status
    if status.get("state") in {"queued", "installing"} and _install_tasks:
        return status
    if not status.get("supported"):
        raise RuntimeError(f"Managed prompt enhancement is not packaged for {status.get('platform')}")
    job_id = uuid.uuid4().hex
    _update_state(
        jobId=job_id,
        state="queued",
        stage="queued",
        message="Waiting to install Managed Local…",
        error=None,
        createdAt=_now(),
        finishedAt=None,
        currentFile=None,
        bytesDownloaded=0,
        bytesTotal=None,
        speedBps=0,
    )
    task = asyncio.create_task(_run_install(job_id))
    _install_tasks.add(task)
    task.add_done_callback(_install_tasks.discard)
    return get_status()


def _thread_count() -> int:
    count = os.cpu_count() or 4
    return max(2, min(8, max(1, count // 2)))


async def _health_ready(timeout_seconds: float = 90.0) -> bool:
    """Confirm port 7071 belongs to Orange's managed Gemma server, not merely any HTTP service."""
    deadline = time.monotonic() + timeout_seconds
    models_url = f"{MANAGED_BASE_URL}/models"
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            with _process_lock:
                process = _server_process
            if process is not None and process.poll() is not None:
                return False
            try:
                response = await client.get(models_url)
                if response.status_code == 200:
                    data = response.json()
                    model_ids = {
                        str(item.get("id") or "")
                        for item in (data.get("data") or [])
                        if isinstance(item, dict)
                    }
                    if MANAGED_MODEL_ID in model_ids:
                        return True
            except (httpx.HTTPError, ValueError, TypeError):
                pass
            await asyncio.sleep(0.4)
    return False


async def ensure_server_ready() -> None:
    status = get_status()
    if not status.get("installed"):
        raise RuntimeError("Managed Local is not installed yet. Install Gemma 4 from Admin → General Settings first.")
    if _process_running():
        if await _health_ready(4.0):
            return

    executable = _server_executable()
    if not executable:
        raise RuntimeError("Managed Local llama.cpp runtime is missing. Repair the installation from Admin.")

    global _server_process, _server_log
    with _process_lock:
        if _server_process is None or _server_process.poll() is not None:
            os.makedirs(RUNTIME_ROOT, exist_ok=True)
            log_path = os.path.join(RUNTIME_ROOT, "llama-server.log")
            _server_log = open(log_path, "a", encoding="utf-8")
            command = [
                executable,
                "--model", MODEL_PATH,
                "--alias", MANAGED_MODEL_ID,
                "--host", "127.0.0.1",
                "--port", str(MANAGED_PORT),
                "--ctx-size", "4096",
                "--threads", str(_thread_count()),
                "--n-gpu-layers", "0",
                "--sleep-idle-seconds", "300",
            ]
            _server_process = subprocess.Popen(
                command,
                cwd=os.path.dirname(executable),
                stdin=subprocess.DEVNULL,
                stdout=_server_log,
                stderr=subprocess.STDOUT,
            )

    if not await _health_ready(90.0):
        stop_server()
        raise RuntimeError("Managed Local could not start llama-server. Check workflows/.runtime/prompt-enhancer/llama-server.log.")


def stop_server() -> None:
    global _server_process, _server_log
    with _process_lock:
        process = _server_process
        _server_process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if _server_log is not None:
            try:
                _server_log.close()
            except Exception:
                pass
            _server_log = None


def remove_installation() -> dict:
    stop_server()
    with _state_lock:
        if os.path.isdir(RUNTIME_ROOT):
            shutil.rmtree(RUNTIME_ROOT, ignore_errors=True)
    return get_status()
