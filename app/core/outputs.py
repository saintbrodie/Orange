import mimetypes
import os
from typing import Any, Dict, Iterable, List, Optional


MIME_OVERRIDES = {
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
}

MEDIA_KEYS = ("images", "gifs", "video", "videos", "audio")


def guess_media_type(filename: str, fallback: Optional[str] = None) -> str:
    suffix = os.path.splitext(str(filename or ""))[1].lower()
    if suffix in MIME_OVERRIDES:
        return MIME_OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(str(filename or ""))
    if guessed:
        return guessed
    clean_fallback = str(fallback or "").split(";", 1)[0].strip()
    return clean_fallback or "application/octet-stream"


def _dedupe_key(item: Dict[str, Any]) -> tuple:
    return (
        item.get("filename", ""),
        item.get("subfolder", ""),
        item.get("type", "output"),
    )


def _iter_items(outputs: Dict[str, Any], keys: Iterable[str]):
    for node_id, output_data in outputs.items():
        if not isinstance(output_data, dict):
            continue
        for source_key in keys:
            values = output_data.get(source_key, [])
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict) or not value.get("filename"):
                    continue
                yield str(node_id), source_key, value


def collect_media_outputs(outputs: Dict[str, Any], output_type: str) -> List[Dict[str, Any]]:
    """Flatten Comfy outputs into stable media entries for one Orange output type."""
    requested = str(output_type or "image").lower()
    if requested == "image":
        keys = ("images", "gifs")
    elif requested == "video":
        # GIF/WebP animation nodes commonly publish under `gifs`. Do not treat an
        # ordinary static image as a video fallback merely because a video tool was used.
        keys = ("video", "videos", "gifs", "images")
    elif requested == "audio":
        keys = ("audio",)
    else:
        return []

    seen = set()
    result: List[Dict[str, Any]] = []
    for node_id, source_key, item in _iter_items(outputs, keys):
        media_type = guess_media_type(item.get("filename", ""))
        if requested == "video" and source_key == "images" and not media_type.startswith("video/"):
            continue
        if requested == "audio" and not media_type.startswith("audio/"):
            continue
        if requested == "image" and not media_type.startswith("image/"):
            continue

        key = _dedupe_key(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "index": len(result),
                "node_id": node_id,
                "source_key": source_key,
                "filename": item["filename"],
                "subfolder": item.get("subfolder", ""),
                "type": item.get("type", "output"),
                "media_type": media_type,
            }
        )
    return result


def extract_text_output(outputs: Dict[str, Any]) -> Optional[str]:
    for output_data in outputs.values():
        if not isinstance(output_data, dict):
            continue
        for key in ("text", "string", "messages"):
            value = output_data.get(key)
            if value in (None, "", []):
                continue
            if isinstance(value, list):
                value = value[0] if value else ""
            if isinstance(value, dict):
                for candidate in ("text", "content", "message"):
                    if value.get(candidate):
                        value = value[candidate]
                        break
            if isinstance(value, (str, int, float, bool)):
                return str(value)
    return None
