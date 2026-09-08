import hashlib
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from app.core.config import PROJECT_ROOT

ASSETS_ROOT = os.path.join(PROJECT_ROOT, "workflows", "assets")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def _safe_workflow_filename(workflow_file: str) -> str:
    name = os.path.basename(str(workflow_file or "").strip())
    if not name or name != str(workflow_file or "").strip() or not name.lower().endswith(".json"):
        raise ValueError("Invalid workflow filename")
    return name


def asset_namespace(workflow_file: str) -> str:
    name = _safe_workflow_filename(workflow_file)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "workflow"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}"


def asset_directory(workflow_file: str, create: bool = False) -> str:
    path = os.path.join(ASSETS_ROOT, asset_namespace(workflow_file))
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def safe_asset_name(asset_name: str) -> str:
    name = os.path.basename(str(asset_name or "").strip())
    if not name or name != str(asset_name or "").strip():
        raise ValueError("Invalid asset filename")
    if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Workflow assets must be image files")
    return name


def list_workflow_assets(workflow_file: str) -> List[str]:
    path = asset_directory(workflow_file)
    if not os.path.isdir(path):
        return []
    return sorted(
        name
        for name in os.listdir(path)
        if os.path.isfile(os.path.join(path, name)) and Path(name).suffix.lower() in IMAGE_EXTENSIONS
    )


def workflow_asset_names(workflow_file: str) -> Set[str]:
    return set(list_workflow_assets(workflow_file))


def workflow_asset_path(workflow_file: str, asset_name: str) -> Optional[str]:
    name = safe_asset_name(asset_name)
    path = os.path.join(asset_directory(workflow_file), name)
    return path if os.path.isfile(path) else None


def mapped_input_fields(node_mapping: dict) -> Dict[str, Set[str]]:
    mapped: Dict[str, Set[str]] = {}
    for mapping_name, mapping in (node_mapping or {}).items():
        if mapping_name == "outputText" or not isinstance(mapping, dict):
            continue
        node_id = str(mapping.get("nodeId", "")).strip()
        field = str(mapping.get("field", "")).strip()
        if node_id and field:
            mapped.setdefault(node_id, set()).add(field)
    return mapped


def find_managed_asset_references(
    workflow: dict,
    node_mapping: dict,
    workflow_file: str,
) -> List[Tuple[str, str, str, str]]:
    """Return (node_id, field, asset_name, path) for local static image references.

    Only unmapped string inputs are considered. This keeps user-supplied image
    mappings authoritative while allowing fixed reference images to travel with
    the workflow.
    """
    available = workflow_asset_names(workflow_file)
    if not available or not isinstance(workflow, dict):
        return []

    mapped = mapped_input_fields(node_mapping)
    references: List[Tuple[str, str, str, str]] = []
    seen = set()

    for raw_node_id, node in workflow.items():
        node_id = str(raw_node_id)
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        for field, value in inputs.items():
            if field in mapped.get(node_id, set()) or not isinstance(value, str):
                continue
            name = os.path.basename(value)
            if name not in available or Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            path = workflow_asset_path(workflow_file, name)
            key = (node_id, field, name)
            if path and key not in seen:
                references.append((node_id, field, name, path))
                seen.add(key)

    return references


def managed_asset_values(workflow_file: str) -> Set[str]:
    """Names that preflight may treat as Orange-managed backend inputs."""
    return workflow_asset_names(workflow_file)
