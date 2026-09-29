from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESTART_FILE = ROOT / "RESTART_REQUIRED"
LOG_DIR = ROOT / "runtime" / "logs"
LOG_FILE = LOG_DIR / "orange.log"
ORANGE_URL = "http://127.0.0.1:7070"
VERBOSE = str(os.environ.get("ORANGE_VERBOSE_LOGS", "")).lower() in {"1", "true", "yes"}

SURFACE_RE = re.compile(r"traceback|\bwarning\b|\berror\b|exception|critical|fatal|failed|failure", re.I)

BANNER = (
    "      ▄▄▄   ▄▄▄·  ▐ ▄  ▄▄ • ▄▄▄ .",
    "▪     ▀▄ █·▐█ ▀█ •█▌▐█▐█ ▀ ▪▀▄.▀·",
    " ▄█▀▄ ▐▀▀▄ ▄█▀▀█ ▐█▐▐▌▄█ ▀█▄▐▀▀▪▄",
    "▐█▌.▐▌▐█•█▌▐█ ▪▐▌██▐█▌▐█▄▪▐█▐█▄▄▌",
    " ▀█▄▀▪.▀  ▀ ▀  ▀ ▀▀ █▪·▀▀▀▀  ▀▀▀ ",
)


def status(name: str, value: str) -> None:
    print(f"  {name:<9} {value}", flush=True)


def print_banner() -> None:
    print()
    for line in BANNER:
        print(line)
    print()


def should_surface(line: str) -> bool:
    if not line or "FutureWarning" in line:
        return False
    return bool(SURFACE_RE.search(line))


def stream_reader(stream, label: str, log_handle, recent: deque[str], output_queue: queue.Queue[tuple[str, str]]) -> None:
    try:
        for raw in iter(stream.readline, ""):
            log_handle.write(raw)
            log_handle.flush()
            line = raw.rstrip("\r\n")
            if line:
                recent.append(line)
            if VERBOSE:
                output_queue.put(("raw", raw))
            elif should_surface(line.strip()):
                output_queue.put((label, line.strip()))
    finally:
        try:
            stream.close()
        except Exception:
            pass


def drain_output(output_queue: queue.Queue[tuple[str, str]]) -> None:
    while True:
        try:
            label, text = output_queue.get_nowait()
        except queue.Empty:
            return
        if label == "raw":
            sys.stdout.write(text)
            sys.stdout.flush()
        else:
            print(f"  [{label}] {text}", flush=True)


def wait_for_ready(proc: subprocess.Popen[str], output_queue: queue.Queue[tuple[str, str]], timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        drain_output(output_queue)
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(ORANGE_URL + "/", timeout=1.0) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    return False


def terminate(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def show_failure_tail(recent: deque[str]) -> None:
    if not recent:
        return
    print("\n  Last Orange log lines:", flush=True)
    for line in list(recent)[-12:]:
        print(f"    {line}", flush=True)
    print(f"\n  Full log: {LOG_FILE.relative_to(ROOT)}", flush=True)


def run_once(log_handle) -> tuple[int, bool]:
    recent: deque[str] = deque(maxlen=40)
    output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
    args = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "7070",
    ]
    if not VERBOSE:
        args.extend(["--no-access-log", "--log-level", "warning"])

    proc = subprocess.Popen(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    threads = [
        threading.Thread(target=stream_reader, args=(proc.stdout, "Orange", log_handle, recent, output_queue), daemon=True),
        threading.Thread(target=stream_reader, args=(proc.stderr, "Orange", log_handle, recent, output_queue), daemon=True),
    ]
    for thread in threads:
        thread.start()

    if not wait_for_ready(proc, output_queue):
        drain_output(output_queue)
        code = proc.poll()
        if code is None:
            status("Orange", "failed to become ready")
            terminate(proc)
            code = 1
        else:
            status("Orange", f"stopped before ready (exit {code})")
        show_failure_tail(recent)
        return int(code or 1), False

    status("Orange", f"ready   {ORANGE_URL}")

    try:
        while proc.poll() is None:
            drain_output(output_queue)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print()
        status("Orange", "stopping...")
        terminate(proc)
        drain_output(output_queue)
        return 0, False

    drain_output(output_queue)
    code = int(proc.returncode or 0)
    restart = RESTART_FILE.exists()
    if restart:
        try:
            RESTART_FILE.unlink()
        except OSError:
            pass
    return code, restart


def main() -> int:
    os.chdir(ROOT)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        RESTART_FILE.unlink()
    except FileNotFoundError:
        pass

    print_banner()
    status("Orange", "starting...")
    if not VERBOSE:
        status("Logs", str(LOG_DIR.relative_to(ROOT)) + os.sep)
    print()

    with LOG_FILE.open("w", encoding="utf-8", buffering=1) as log_handle:
        while True:
            code, restart = run_once(log_handle)
            if not restart:
                if code:
                    status("Orange", f"stopped (exit {code})")
                return code
            status("Orange", "restarting...")
            time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
