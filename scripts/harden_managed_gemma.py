from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new, count=1):
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch text not found in {path}: {old[:120]!r}")
    file.write_text(text.replace(old, new, count), encoding="utf-8")


replace(
    "app/core/managed_prompt_enhancer.py",
    '''        else:\n            with tarfile.open(archive_path, "r:gz") as archive:\n                for member in archive.getmembers():\n                    _safe_target(staging, member.name)\n                    if member.issym() or member.islnk():\n                        raise RuntimeError("Runtime archive contains unsupported links")\n                archive.extractall(staging)\n''',
    '''        else:\n            with tarfile.open(archive_path, "r:gz") as archive:\n                for member in archive.getmembers():\n                    member_target = _safe_target(staging, member.name)\n                    if member.issym():\n                        link_target = os.path.abspath(os.path.join(os.path.dirname(member_target), member.linkname))\n                        _safe_target(staging, os.path.relpath(link_target, staging))\n                    elif member.islnk():\n                        _safe_target(staging, member.linkname)\n                archive.extractall(staging)\n''',
)
replace(
    "app/core/managed_prompt_enhancer.py",
    '''async def _health_ready(timeout_seconds: float = 90.0) -> bool:\n    deadline = time.monotonic() + timeout_seconds\n    async with httpx.AsyncClient(timeout=2.0) as client:\n        while time.monotonic() < deadline:\n            try:\n                response = await client.get(MANAGED_HEALTH_URL)\n                if response.status_code < 500:\n                    return True\n            except httpx.HTTPError:\n                pass\n            await asyncio.sleep(0.4)\n    return False\n''',
    '''async def _health_ready(timeout_seconds: float = 90.0) -> bool:\n    """Confirm port 7071 belongs to Orange's managed Gemma server, not merely any HTTP service."""\n    deadline = time.monotonic() + timeout_seconds\n    models_url = f"{MANAGED_BASE_URL}/models"\n    async with httpx.AsyncClient(timeout=2.0) as client:\n        while time.monotonic() < deadline:\n            with _process_lock:\n                process = _server_process\n            if process is not None and process.poll() is not None:\n                return False\n            try:\n                response = await client.get(models_url)\n                if response.status_code == 200:\n                    data = response.json()\n                    model_ids = {\n                        str(item.get("id") or "")\n                        for item in (data.get("data") or [])\n                        if isinstance(item, dict)\n                    }\n                    if MANAGED_MODEL_ID in model_ids:\n                        return True\n            except (httpx.HTTPError, ValueError, TypeError):\n                pass\n            await asyncio.sleep(0.4)\n    return False\n''',
)
replace(
    "app/core/llm.py",
    '''    timeout = httpx.Timeout(_timeout_seconds())\n    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:\n''',
    '''    # A sleeping managed model may need to reload several GB from disk before\n    # producing its first token, so give the private local runtime more headroom\n    # than normal network providers.\n    timeout_seconds = max(120.0, _timeout_seconds()) if provider == "managed" else _timeout_seconds()\n    timeout = httpx.Timeout(timeout_seconds)\n    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:\n''',
)

print("Managed Local runtime hardening applied")
