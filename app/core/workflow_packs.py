import json
import os
import re
import shutil
import tempfile
import urllib.request
from copy import deepcopy

from app.core.config import PROJECT_ROOT

PACKS_DIR = os.path.join(PROJECT_ROOT, "workflow-packs")
ACTIVE_WORKFLOWS_DIR = os.path.join(PROJECT_ROOT, "workflows")
DEFAULT_WORKFLOWS_DIR = os.path.join(ACTIVE_WORKFLOWS_DIR, "defaults")

_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")
_PACK_DISPLAY_ORDER = {
    "z-image-turbo": 0,
    "krea-2-turbo": 10,
    "klein-9b-edit": 20,
    "seedvr2-7b-upscale": 30,
}


def list_workflow_packs() -> list[dict]:
    packs = []
    if not os.path.isdir(PACKS_DIR):
        return packs
    for entry in sorted(os.listdir(PACKS_DIR)):
        manifest_path = os.path.join(PACKS_DIR, entry, "manifest.json")
        if not os.path.isfile(manifest_path):
            continue
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest["id"] = manifest.get("id") or entry
            packs.append(manifest)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(
        packs,
        key=lambda pack: (
            _PACK_DISPLAY_ORDER.get(str(pack.get("id") or ""), 1000),
            str(pack.get("name") or pack.get("id") or "").lower(),
        ),
    )


def get_workflow_pack(pack_id: str) -> dict:
    safe_id = os.path.basename(pack_id)
    if safe_id != pack_id:
        raise ValueError("Invalid workflow pack id")
    path = os.path.join(PACKS_DIR, safe_id, "manifest.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Workflow pack not found: {pack_id}")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest["id"] = manifest.get("id") or safe_id
    return manifest


def resolve_models_root(explicit: str | None = None) -> str | None:
    candidates = []
    if explicit:
        candidates.append(explicit)
    env_root = os.environ.get("ORANGE_MODELS_ROOT", "").strip()
    if env_root:
        candidates.append(env_root)
    comfy_dir = os.environ.get("ORANGE_COMFYUI_DIR", "").strip()
    if comfy_dir:
        candidates.append(os.path.join(comfy_dir, "models"))

    parent = os.path.dirname(PROJECT_ROOT)
    home = os.path.expanduser("~")
    candidates.extend(
        [
            os.path.join(parent, "ComfyUI", "models"),
            os.path.join(parent, "comfyui", "ComfyUI", "models"),
            os.path.join(home, "ComfyUI", "models"),
            os.path.join(home, "ComfyUI_windows_portable", "ComfyUI", "models"),
        ]
    )

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.abspath(os.path.expanduser(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isdir(normalized):
            return normalized
    return None


def _parse_version(value: object) -> tuple[int, int, int] | None:
    match = _VERSION_RE.search(str(value or ""))
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def summarize_system_stats(system_stats: dict | None) -> dict:
    """Normalize the useful hardware hints returned by ComfyUI /system_stats."""
    stats = system_stats if isinstance(system_stats, dict) else {}
    system = stats.get("system") if isinstance(stats.get("system"), dict) else {}
    devices = stats.get("devices") if isinstance(stats.get("devices"), list) else []

    def _vram(device: dict) -> int:
        raw = device.get("vram_total", device.get("torch_vram_total", 0))
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    valid_devices = [device for device in devices if isinstance(device, dict)]
    device = max(valid_devices, key=_vram, default={})
    name = str(device.get("name") or "").strip()
    device_type = str(device.get("type") or "").strip().lower()
    vram_bytes = _vram(device)
    vram_gb = round(vram_bytes / (1024 ** 3), 1) if vram_bytes else None

    comfy_version = str(
        system.get("comfyui_version")
        or system.get("comfyuiVersion")
        or stats.get("comfyui_version")
        or ""
    ).strip()
    torch_version = str(
        system.get("pytorch_version")
        or system.get("torch_version")
        or stats.get("pytorch_version")
        or ""
    ).strip()

    name_lower = name.lower()
    is_nvidia = "nvidia" in name_lower or device_type in {"cuda", "nvidia"}
    is_amd = any(token in name_lower for token in ("amd", "radeon")) or "rocm" in device_type
    version_tuple = _parse_version(comfy_version)
    comfy_has_native_int8 = version_tuple is not None and version_tuple >= (0, 27, 0)

    int8_convrot = bool(is_nvidia and not is_amd and comfy_has_native_int8)

    return {
        "deviceName": name or None,
        "deviceType": device_type or None,
        "vramGb": vram_gb,
        "comfyuiVersion": comfy_version or None,
        "pytorchVersion": torch_version or None,
        "int8ConvRot": int8_convrot,
    }


def _pick_variant(model: dict, hardware: dict) -> dict:
    variants = model.get("variants")
    if not isinstance(variants, list) or not variants:
        return dict(model)

    normalized = [variant for variant in variants if isinstance(variant, dict)]
    if not normalized:
        raise ValueError(f"Model '{model.get('id', 'unknown')}' has no valid variants")

    by_precision = {str(item.get("precision", "")).lower(): item for item in normalized}

    int8 = by_precision.get("int8")
    if int8 and hardware.get("int8ConvRot"):
        selected = int8
    else:
        vram_gb = hardware.get("vramGb")
        try:
            threshold = float(model.get("bf16MinVramGb", 999))
        except (TypeError, ValueError):
            threshold = 999
        bf16 = by_precision.get("bf16")
        fp8 = by_precision.get("fp8")
        if bf16 and isinstance(vram_gb, (int, float)) and vram_gb >= threshold:
            selected = bf16
        elif fp8:
            selected = fp8
        elif bf16:
            selected = bf16
        else:
            selected = normalized[0]

    result = dict(selected)
    result["id"] = model.get("id")
    result["folder"] = model.get("folder")
    if model.get("sourceNote"):
        result["sourceNote"] = model["sourceNote"]
    return result


def select_model_dependencies(pack_id: str, system_stats: dict | None = None) -> list[dict]:
    manifest = get_workflow_pack(pack_id)
    hardware = summarize_system_stats(system_stats)
    selected = []
    for model in manifest.get("models", []):
        if not isinstance(model, dict):
            continue
        item = _pick_variant(model, hardware)
        item["id"] = item.get("id") or model.get("id")
        item["folder"] = item.get("folder") or model.get("folder")
        if not item.get("precision"):
            item["precision"] = model.get("precision")
        selected.append(item)
    return selected


def _selected_lookup(selected_models: list[dict]) -> dict[str, dict]:
    return {
        str(item.get("id")): item
        for item in selected_models
        if isinstance(item, dict) and item.get("id")
    }


def materialize_workflow_pack(pack_id: str, selected_models: list[dict]) -> str:
    """Copy a curated workflow into active state and bind selected model filenames."""
    manifest = get_workflow_pack(pack_id)
    workflow_file = os.path.basename(str(manifest.get("workflowFile") or "").strip())
    if not workflow_file or not workflow_file.lower().endswith(".json"):
        raise ValueError(f"Workflow pack '{pack_id}' has an invalid workflowFile")

    source = os.path.join(DEFAULT_WORKFLOWS_DIR, workflow_file)
    if not os.path.isfile(source):
        raise FileNotFoundError(f"Workflow pack source not found: {workflow_file}")
    with open(source, "r", encoding="utf-8") as handle:
        workflow = json.load(handle)

    selected = _selected_lookup(selected_models)
    for binding in manifest.get("bindings", []):
        if not isinstance(binding, dict):
            continue
        model = selected.get(str(binding.get("modelId")))
        if not model:
            continue
        node_id = str(binding.get("nodeId") or "")
        field = str(binding.get("field") or "")
        node = workflow.get(node_id)
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict) or not field:
            raise ValueError(f"Invalid model binding in pack '{pack_id}': {binding}")
        node["inputs"][field] = model["filename"]

    os.makedirs(ACTIVE_WORKFLOWS_DIR, exist_ok=True)
    destination = os.path.join(ACTIVE_WORKFLOWS_DIR, workflow_file)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{workflow_file}.", suffix=".tmp", dir=ACTIVE_WORKFLOWS_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(workflow, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, destination)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return destination


def tool_config_for_pack(pack_id: str) -> dict:
    manifest = get_workflow_pack(pack_id)
    tool = manifest.get("tool")
    if not isinstance(tool, dict) or not tool.get("id"):
        raise ValueError(f"Workflow pack '{pack_id}' does not declare a tool")
    return deepcopy(tool)


def _put_z_image_first(tools: list[dict]) -> list[dict]:
    indexed = list(enumerate(tools))
    indexed.sort(
        key=lambda pair: (
            0 if isinstance(pair[1], dict) and pair[1].get("id") == "z-image" else 1,
            pair[0],
        )
    )
    return [tool for _index, tool in indexed]


def add_pack_tool_to_config(config: dict, pack_id: str) -> dict:
    updated = deepcopy(config)
    tools = list(updated.get("tools") or [])
    tool = tool_config_for_pack(pack_id)
    tools = [existing for existing in tools if isinstance(existing, dict) and existing.get("id") != tool.get("id")]
    tools.append(tool)
    updated["tools"] = _put_z_image_first(tools)
    if pack_id == "klein-9b-edit" and not updated.get("modifyTool"):
        updated["modifyTool"] = "klein-edit"
    return updated


def install_workflow_pack(
    pack_id: str,
    models_root: str,
    system_stats: dict | None = None,
    materialize: bool = False,
    selected_models: list[dict] | None = None,
) -> dict:
    manifest = get_workflow_pack(pack_id)
    root = os.path.abspath(os.path.expanduser(models_root))
    if not os.path.isdir(root):
        raise FileNotFoundError(f"ComfyUI models directory does not exist: {root}")

    hardware = summarize_system_stats(system_stats)
    selected_models = list(selected_models) if selected_models is not None else select_model_dependencies(pack_id, system_stats)
    installed = []
    skipped = []
    failures = []
    for model in selected_models:
        if model.get("reuseExisting"):
            skipped.append(str(model.get("filename") or "existing model"))
            continue
        folder = str(model.get("folder", "")).strip()
        filename = os.path.basename(str(model.get("filename", "")).strip())
        url = str(model.get("url", "")).strip()
        if not folder or not filename or not url:
            failures.append({"filename": filename or "unknown", "error": "Invalid model manifest entry"})
            continue
        destination_dir = os.path.join(root, folder)
        os.makedirs(destination_dir, exist_ok=True)
        destination = os.path.join(destination_dir, filename)
        if os.path.exists(destination):
            skipped.append(destination)
            continue
        try:
            _download_file(url, destination)
            installed.append(destination)
        except Exception as exc:
            failures.append({"filename": filename, "error": str(exc)})

    workflow_path = None
    if materialize and not failures:
        workflow_path = materialize_workflow_pack(pack_id, selected_models)

    return {
        "pack": manifest.get("id", pack_id),
        "modelsRoot": root,
        "hardware": hardware,
        "selectedModels": selected_models,
        "installed": installed,
        "skipped": skipped,
        "failures": failures,
        "workflowPath": workflow_path,
    }


def _download_file(url: str, destination: str) -> None:
    part_path = destination + ".part"
    try:
        if os.path.exists(part_path):
            os.remove(part_path)
        request = urllib.request.Request(url, headers={"User-Agent": "Orange/1.0"})
        with urllib.request.urlopen(request) as response, open(part_path, "wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(part_path, destination)
    finally:
        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass
