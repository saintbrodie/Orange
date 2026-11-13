"""Resolve portable model filenames against a selected ComfyUI backend.

Only model-file selectors participate. Images, sampler names, and other enums
remain owned by their existing validation paths. A resolution never mutates the
source workflow, and a binding never changes model name or precision.
"""

import json
import os
import tempfile
import threading
import time
from copy import deepcopy
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import PROJECT_ROOT

BINDINGS_PATH = os.path.join(PROJECT_ROOT, "workflows", ".runtime", "model-bindings.json")
INVENTORY_TTL = 60.0
_inventory = {}
_store_lock = threading.RLock()
MODEL_EXTENSIONS = {".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx"}


def normalize_backend(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    hostname = (parts.hostname or "").lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = parts.port
    if port and not ((parts.scheme.lower() == "http" and port == 80) or (parts.scheme.lower() == "https" and port == 443)):
        hostname += f":{port}"
    return urlunsplit((parts.scheme.lower(), hostname, parts.path.rstrip("/"), "", ""))


def normalized_path(value: str) -> str:
    return str(value).replace("\\", "/")


def model_filename(value: str) -> str:
    return normalized_path(value).rsplit("/", 1)[-1]


def input_options(node_def: dict, field: str) -> list | None:
    inputs = node_def.get("input", {}) if isinstance(node_def, dict) else {}
    if not isinstance(inputs, dict):
        return None
    for section in ("required", "optional", "hidden"):
        fields = inputs.get(section)
        if not isinstance(fields, dict):
            continue
        spec = fields.get(field)
        if isinstance(spec, (list, tuple)) and spec:
            if isinstance(spec[0], list):
                return spec[0]
            if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                options = spec[1].get("options")
                if isinstance(options, list):
                    return options
    return None


def model_category(class_type: str, field: str) -> str:
    name = field.lower()
    if name == "vae_name":
        return "vae"
    if name in {"ckpt_name", "checkpoint_name"}:
        return "checkpoints"
    if name.startswith("clip_name") or name.startswith("text_encoder_name"):
        return "text_encoders"
    if name == "lora_name":
        return "loras"
    if name in {"unet_name", "diffusion_model"}:
        return "diffusion_models"
    if name == "control_net_name":
        return "controlnet"
    if name == "clip_vision_name":
        return "clip_vision"
    if name == "model_name" and "upscale" in class_type.lower():
        return "upscale_models"
    # Custom loaders retain their own namespace rather than sharing a binding
    # with an unrelated model category that happens to use the same filename.
    return f"{class_type}:{field}"


def model_references(workflow: dict, object_info: dict, node_mapping: dict | None = None) -> list[dict]:
    mapped = {(str(m.get("nodeId")), m.get("field")) for key, m in (node_mapping or {}).items()
              if key != "outputText" and isinstance(m, dict)}
    references = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for field, value in inputs.items():
            if not isinstance(value, str) or (str(node_id), field) in mapped:
                continue
            if PurePosixPath(normalized_path(value)).suffix.lower() not in MODEL_EXTENSIONS:
                continue
            options = input_options(object_info.get(class_type, {}), field)
            if options is None:
                continue
            filename = model_filename(value)
            references.append({
                "node_id": str(node_id), "class_type": class_type, "field": field,
                "category": model_category(class_type, field), "filename": filename,
                "requested": value,
                "options": sorted({o for o in options if isinstance(o, str) and model_filename(o) == filename}),
            })
    return references


def _read_store() -> dict:
    try:
        with open(BINDINGS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("backends"), dict):
        raise ValueError("Invalid model bindings file")
    return data["backends"]


def _identity(reference: dict) -> str:
    return json.dumps([reference["category"], reference["filename"]], separators=(",", ":"))


def saved_binding(backend_url: str, category: str, filename: str) -> str | None:
    with _store_lock:
        return _read_store().get(normalize_backend(backend_url), {}).get(_identity({"category": category, "filename": filename}))


def save_binding(backend_url: str, reference: dict, path: str | None) -> None:
    if path is not None and path not in reference["options"]:
        raise ValueError("Select an available path with the exact same model filename")
    with _store_lock:
        backends = _read_store()
        bindings = backends.setdefault(normalize_backend(backend_url), {})
        if path is None:
            bindings.pop(_identity(reference), None)
        else:
            bindings[_identity(reference)] = path
        directory = os.path.dirname(BINDINGS_PATH)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".model-bindings-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "backends": backends}, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, BINDINGS_PATH)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)


def matching_option(options: list, requested: str, bound: str | None = None) -> tuple[str | None, str]:
    paths = [o for o in options if isinstance(o, str)]
    # The backend's exact spelling (including separators) is what we submit.
    for target, reason in ((bound, "binding"), (requested, "exact")):
        if target is None:
            continue
        matches = [o for o in paths if normalized_path(o) == normalized_path(target)]
        if len(matches) == 1:
            return matches[0], reason
        if len(matches) > 1 and target in matches:
            return target, reason
    matches = [o for o in paths if model_filename(o) == model_filename(requested)]
    if len(matches) == 1:
        return matches[0], "filename"
    return None, "ambiguous" if matches else "missing"


def resolve_models(workflow: dict, object_info: dict, backend_url: str, node_mapping: dict | None = None) -> dict:
    resolved = deepcopy(workflow)
    with _store_lock:
        bindings = _read_store().get(normalize_backend(backend_url), {})
    references = model_references(workflow, object_info, node_mapping)
    errors = []
    for ref in references:
        bound = bindings.get(_identity(ref))
        path, reason = matching_option(ref["options"], ref["requested"], bound)
        ref.update({"resolved": path, "reason": reason, "binding": bound,
                    "stale_binding": bool(bound and reason != "binding")})
        if path is not None:
            resolved[ref["node_id"]]["inputs"][ref["field"]] = path
        else:
            message = (f"Multiple paths contain '{ref['filename']}'. Select a model binding for this backend."
                       if reason == "ambiguous" else f"Model '{ref['filename']}' ({ref['category']}) is missing on this backend.")
            errors.append({"code": f"model_{reason}", "message": message,
                           "node_id": ref["node_id"], "field": ref["field"]})
    return {"workflow": resolved, "models": references, "errors": errors}


def cache_inventory(url: str, object_info: dict) -> None:
    _inventory[normalize_backend(url)] = (time.monotonic(), object_info)


def invalidate_inventory(url: str) -> None:
    _inventory.pop(normalize_backend(url), None)


async def backend_inventory(client: httpx.AsyncClient, url: str, refresh: bool = False) -> dict:
    cached = _inventory.get(normalize_backend(url))
    if not refresh and cached and time.monotonic() - cached[0] < INVENTORY_TTL:
        return cached[1]
    response = await client.get(f"{url.rstrip('/')}/object_info", timeout=httpx.Timeout(12.0, connect=5.0))
    response.raise_for_status()
    info = response.json()
    if not isinstance(info, dict):
        raise ValueError("/object_info response was not an object")
    cache_inventory(url, info)
    return info
