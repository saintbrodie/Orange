import asyncio
import os
import shutil
from copy import deepcopy

import httpx

DOWNLOAD_SPACE_BUFFER_BYTES = 512 * 1024 * 1024
_size_cache: dict[str, int | None] = {}


async def _remote_size(client: httpx.AsyncClient, url: str) -> int | None:
    if not url:
        return None
    if url in _size_cache:
        return _size_cache[url]
    size = None
    try:
        response = await client.head(url)
        if response.is_success:
            raw = response.headers.get("Content-Length")
            if raw:
                size = int(raw)
    except (httpx.HTTPError, TypeError, ValueError):
        size = None
    _size_cache[url] = size
    return size


async def enrich_download_plan(plan: list[dict]) -> list[dict]:
    enriched = [deepcopy(item) for item in (plan or []) if isinstance(item, dict)]
    if not enriched:
        return enriched
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        sizes = await asyncio.gather(
            *(_remote_size(client, str(item.get("url") or "")) for item in enriched)
        )
    for item, size in zip(enriched, sizes):
        if size is not None:
            item["bytesTotal"] = size
    return enriched


def download_summary(plan: list[dict]) -> dict:
    files = [item for item in (plan or []) if isinstance(item, dict)]
    known = 0
    known_count = 0
    for item in files:
        value = item.get("bytesTotal")
        if isinstance(value, (int, float)) and value >= 0:
            known += int(value)
            known_count += 1
    return {
        "downloadFileCount": len(files),
        "downloadBytesTotal": known,
        "downloadBytesKnown": known,
        "downloadSizeComplete": bool(files) and known_count == len(files),
    }


def disk_space(path: str | None) -> dict | None:
    if not path:
        return None
    current = os.path.abspath(os.path.expanduser(path))
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    try:
        usage = shutil.disk_usage(current)
    except OSError:
        return None
    return {
        "path": current,
        "totalBytes": int(usage.total),
        "usedBytes": int(usage.used),
        "freeBytes": int(usage.free),
    }


def space_requirement(plan: list[dict], models_root: str | None) -> dict:
    summary = download_summary(plan)
    disk = disk_space(models_root)
    required = int(summary["downloadBytesKnown"]) + (DOWNLOAD_SPACE_BUFFER_BYTES if summary["downloadFileCount"] else 0)
    insufficient = bool(disk and required and int(disk["freeBytes"]) < required)
    return {
        **summary,
        "diskSpace": disk,
        "requiredBytesWithBuffer": required,
        "spaceBufferBytes": DOWNLOAD_SPACE_BUFFER_BYTES if summary["downloadFileCount"] else 0,
        "insufficientDiskSpace": insufficient,
    }
