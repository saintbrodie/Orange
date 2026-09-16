import json
import os
from copy import deepcopy

from app.core.config import PROJECT_ROOT
from app.core.workflow_packs import (
    get_workflow_pack,
    select_model_dependencies,
    summarize_system_stats,
)

DEFAULT_WORKFLOWS_DIR = os.path.join(PROJECT_ROOT, "workflows", "defaults")


def _load_curated_workflow(manifest: dict) -> dict:
    workflow_file = os.path.basename(str(manifest.get("workflowFile") or "").strip())
    if not workflow_file:
        raise ValueError("Workflow pack has no workflowFile")
    path = os.path.join(DEFAULT_WORKFLOWS_DIR, workflow_file)
    with open(path, "r", encoding="utf-8") as handle:
        workflow = json.load(handle)
    if not isinstance(workflow, dict):
        raise ValueError(f"Curated workflow is invalid: {workflow_file}")
    return workflow


def _input_options(node_def: dict, field: str) -> list | None:
    inputs = node_def.get("input") if isinstance(node_def, dict) else None
    if not isinstance(inputs, dict):
        return None
    for section_name in ("required", "optional", "hidden"):
        section = inputs.get(section_name)
        if not isinstance(section, dict):
            continue
        spec = section.get(field)
        if isinstance(spec, (list, tuple)) and spec and isinstance(spec[0], list):
            return spec[0]
    return None


def _variants(model: dict) -> list[dict]:
    declared = model.get("variants")
    if not isinstance(declared, list) or not declared:
        declared = [model]
    result = []
    for variant in declared:
        if not isinstance(variant, dict):
            continue
        item = deepcopy(variant)
        item["id"] = model.get("id")
        item["folder"] = model.get("folder")
        item["precision"] = item.get("precision") or model.get("precision")
        if model.get("sourceNote") and not item.get("sourceNote"):
            item["sourceNote"] = model["sourceNote"]
        result.append(item)
    return result


def _supported_variant(variant: dict, hardware: dict) -> bool:
    if variant.get("requiresInt8ConvRot") and not hardware.get("int8ConvRot"):
        return False
    return True


def _matching_option(options: list, filename: str | None) -> str | None:
    target = str(filename or "").replace("\\", "/")
    if not target:
        return None
    target_base = target.rsplit("/", 1)[-1]
    for option in options:
        value = str(option or "").replace("\\", "/")
        if value == target or value.rsplit("/", 1)[-1] == target_base:
            return str(option)
    return None


def plan_selected_models(selected_models: list[dict], models_root: str | None = None) -> list[dict]:
    root = os.path.abspath(os.path.expanduser(models_root)) if models_root else None
    plan = []
    for model in selected_models:
        if not isinstance(model, dict):
            continue
        folder = str(model.get("folder") or "").strip()
        filename = os.path.basename(str(model.get("filename") or "").strip())
        destination = os.path.join(root, folder, filename) if root and folder and filename else None
        plan.append(
            {
                "id": model.get("id"),
                "folder": folder or None,
                "filename": filename or None,
                "precision": model.get("precision"),
                "url": model.get("url"),
                "sourceNote": model.get("sourceNote"),
                "destination": destination,
                "exists": bool(destination and os.path.exists(destination)),
            }
        )
    return plan


def plan_workflow_pack(pack_id: str, system_stats: dict | None = None, models_root: str | None = None) -> list[dict]:
    return plan_selected_models(select_model_dependencies(pack_id, system_stats), models_root)


def selection_for_install(inspection: dict) -> list[dict]:
    """Keep compatible existing variants and download only dependencies that are actually missing."""
    selected = [deepcopy(item) for item in (inspection.get("selectedModels") or []) if isinstance(item, dict)]
    selected.extend(
        deepcopy(item)
        for item in (inspection.get("recommendedDownloads") or [])
        if isinstance(item, dict)
    )
    return selected


def inspect_workflow_pack(pack_id: str, object_info: dict, system_stats: dict | None = None) -> dict:
    manifest = get_workflow_pack(pack_id)
    workflow = _load_curated_workflow(manifest)
    hardware = summarize_system_stats(system_stats)
    preferred = {
        str(item.get("id")): item
        for item in select_model_dependencies(pack_id, system_stats)
        if isinstance(item, dict) and item.get("id")
    }

    missing_nodes = sorted(
        {
            str(node.get("class_type"))
            for node in workflow.values()
            if isinstance(node, dict)
            and node.get("class_type")
            and not isinstance(object_info.get(str(node.get("class_type"))), dict)
        }
    )

    binding_by_model = {}
    for binding in manifest.get("bindings", []):
        if isinstance(binding, dict) and binding.get("modelId"):
            binding_by_model.setdefault(str(binding["modelId"]), binding)

    selected_existing = []
    missing_models = []
    unknown_models = []

    for model in manifest.get("models", []):
        if not isinstance(model, dict) or not model.get("id"):
            continue
        model_id = str(model["id"])
        binding = binding_by_model.get(model_id)
        if not binding:
            unknown_models.append({"id": model_id, "reason": "Pack has no model binding"})
            continue

        node_id = str(binding.get("nodeId") or "")
        field = str(binding.get("field") or "")
        node = workflow.get(node_id)
        class_type = node.get("class_type") if isinstance(node, dict) else None
        node_def = object_info.get(class_type) if class_type else None
        options = _input_options(node_def, field) if isinstance(node_def, dict) else None
        variants = [item for item in _variants(model) if _supported_variant(item, hardware)]
        preferred_model = preferred.get(model_id)

        if options is None:
            unknown_models.append(
                {
                    "id": model_id,
                    "folder": model.get("folder"),
                    "nodeId": node_id or None,
                    "field": field or None,
                    "classType": class_type,
                    "reason": "ComfyUI did not expose a model inventory for this loader field",
                }
            )
            continue

        existing = []
        for variant in variants:
            matched = _matching_option(options, variant.get("filename"))
            if not matched:
                continue
            bound = deepcopy(variant)
            bound["declaredFilename"] = variant.get("filename")
            bound["filename"] = matched
            bound["reuseExisting"] = True
            existing.append(bound)

        chosen = None
        if preferred_model:
            preferred_filename = os.path.basename(str(preferred_model.get("filename") or ""))
            chosen = next(
                (
                    item
                    for item in existing
                    if os.path.basename(str(item.get("declaredFilename") or item.get("filename") or "")) == preferred_filename
                ),
                None,
            )
        if chosen is None and existing:
            chosen = existing[0]

        if chosen is not None:
            selected_existing.append(chosen)
            continue

        candidate_names = [item.get("filename") for item in variants if item.get("filename")]
        recommended = preferred_model or (variants[0] if variants else None)
        missing_models.append(
            {
                "id": model_id,
                "folder": model.get("folder"),
                "availableCandidates": candidate_names,
                "recommendedDownload": deepcopy(recommended) if recommended else None,
            }
        )

    ready = not missing_nodes and not missing_models and not unknown_models
    return {
        "pack": manifest.get("id", pack_id),
        "name": manifest.get("name"),
        "ready": ready,
        "hardware": hardware,
        "selectedModels": selected_existing,
        "missingModels": missing_models,
        "missingNodes": missing_nodes,
        "unknownModels": unknown_models,
        "recommendedDownloads": [item["recommendedDownload"] for item in missing_models if item.get("recommendedDownload")],
    }
