from __future__ import annotations

import json
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
COLOR = not os.environ.get("NO_COLOR") and str(os.environ.get("ORANGE_COLOR", "1")).lower() not in {"0", "false", "no"}
EVENT_PREFIX = "ORANGE_EVENT "

SURFACE_RE = re.compile(r"traceback|\bwarning\b|\berror\b|exception|critical|fatal|failed|failure", re.I)

ANSI = {
    "orange": "\033[38;5;208m",
    "green": "\033[38;5;82m",
    "cyan": "\033[38;5;45m",
    "magenta": "\033[38;5;213m",
    "yellow": "\033[38;5;220m",
    "red": "\033[38;5;196m",
    "dim": "\033[38;5;245m",
    "reset": "\033[0m",
}

BANNER = (
    "      ▄▄▄   ▄▄▄·  ▐ ▄  ▄▄ • ▄▄▄ .",
    "▪     ▀▄ █·▐█ ▀█ •█▌▐█▐█ ▀ ▪▀▄.▀·",
    " ▄█▀▄ ▐▀▀▄ ▄█▀▀█ ▐█▐▐▌▄█ ▀█▄▐▀▀▪▄",
    "▐█▌.▐▌▐█•█▌▐█ ▪▐▌██▐█▌▐█▄▪▐█▐█▄▄▌",
    " ▀█▄▀▪.▀  ▀ ▀  ▀ ▀▀ █▪·▀▀▀▀  ▀▀▀ ",
)


def paint(text: str, tone: str) -> str:
    if not COLOR:
        return text
    return f"{ANSI[tone]}{text}{ANSI['reset']}"


def value_tone(value: str) -> str:
    lowered = value.lower()
    if "ready" in lowered or "complete" in lowered:
        return "green"
    if "fail" in lowered or "stopped" in lowered or "error" in lowered:
        return "red"
    if "starting" in lowered or "working" in lowered or "restarting" in lowered:
        return "yellow"
    return "dim"


def status(name: str, value: str) -> None:
    label_tone = "orange" if name == "Orange" else "cyan" if name == "ComfyUI" else "dim"
    label = paint(f"{name:<9}", label_tone)
    print(f"  {label} {paint(value, value_tone(value))}", flush=True)


def print_banner() -> None:
    print()
    for line in BANNER:
        print(paint(line, "orange"))
    print()


def render_event(payload_text: str) -> None:
    try:
        event = json.loads(payload_text)
    except (TypeError, ValueError):
        print(f"  {paint('[Orange]', 'orange')} {payload_text}", flush=True)
        return

    kind = str(event.get("kind", "activity")).lower()
    state = str(event.get("state", "info")).lower()
    message = str(event.get("message", "")).strip()
    label = "Generate" if kind == "generation" else "LLM" if kind == "llm" else "Orange"
    label_tone = "orange" if kind == "generation" else "magenta" if kind == "llm" else "cyan"
    state_tone = "green" if state == "complete" else "red" if state == "failed" else "yellow" if state == "working" else "cyan"
    print(f"  {paint(f'[{label}]', label_tone):<20} {paint(message, state_tone)}", flush=True)


def should_surface(line: str) -> bool:
    if not line or "FutureWarning" in line:
        return False
    return bool(SURFACE_RE.search(line))


def stream_reader(stream, log_handle, recent: deque[str], output_queue: queue.Queue[tuple[str, str]]) -> None:
    try:
        for raw in iter(stream.readline, ""):
            log_handle.write(raw)
            log_handle.flush()
            line = raw.rstrip("\r\n")
            if line:
                recent.append(line)
            if line.startswith(EVENT_PREFIX):
                output_queue.put(("event", line[len(EVENT_PREFIX):]))
            elif VERBOSE:
                output_queue.put(("raw", raw))
            elif should_surface(line.strip()):
                output_queue.put(("Orange", line.strip()))
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
        elif label == "event":
            render_event(text)
        else:
            print(f"  {paint(f'[{label}]', 'red')} {text}", flush=True)


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
            proc.wait(timeout=2)
        except Exception:
            pass


def finish_reader(reader: threading.Thread, output_queue: queue.Queue[tuple[str, str]]) -> None:
    reader.join(timeout=1)
    drain_output(output_queue)


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
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if proc.stdout is None:
        raise RuntimeError("Orange log stream was not created")

    reader = threading.Thread(
        target=stream_reader,
        args=(proc.stdout, log_handle, recent, output_queue),
        daemon=True,
    )
    reader.start()

    if not wait_for_ready(proc, output_queue):
        code = proc.poll()
        if code is None:
            status("Orange", "failed to become ready")
            terminate(proc)
            code = 1
        else:
            status("Orange", f"stopped before ready (exit {code})")
        finish_reader(reader, output_queue)
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
        finish_reader(reader, output_queue)
        return 0, False

    finish_reader(reader, output_queue)
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
