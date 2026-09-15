import json
import os
import shutil
import urllib.request

from app.core.config import PROJECT_ROOT

PACKS_DIR = os.path.join(PROJECT_ROOT, "workflow-packs")


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
    return packs


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


def install_workflow_pack(pack_id: str, models_root: str) -> dict:
    manifest = get_workflow_pack(pack_id)
    root = os.path.abspath(os.path.expanduser(models_root))
    if not os.path.isdir(root):
        raise FileNotFoundError(f"ComfyUI models directory does not exist: {root}")

    installed = []
    skipped = []
    failures = []
    for model in manifest.get("models", []):
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

    return {
        "pack": manifest.get("id", pack_id),
        "modelsRoot": root,
        "installed": installed,
        "skipped": skipped,
        "failures": failures,
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
