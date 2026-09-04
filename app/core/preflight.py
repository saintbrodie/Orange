import asyncio
import time
from collections import defaultdict
from typing import Any

import httpx


def _issue(code: str, message: str, **context) -> dict:
    issue = {"code": code, "message": message}
    issue.update({key: value for key, value in context.items() if value is not None})
    return issue


def validate_workflow_structure(workflow: Any) -> dict:
    """Validate that a workflow looks like ComfyUI API-format JSON."""
    errors = []
    warnings = []

    if not isinstance(workflow, dict) or not workflow:
        errors.append(_issue("workflow_invalid", "Workflow must be a non-empty JSON object."))
        return {"errors": errors, "warnings": warnings}

    if isinstance(workflow.get("nodes"), list):
        errors.append(
            _issue(
                "workflow_ui_format",
                "This looks like a ComfyUI UI workflow. Export it using Save (API format).",
            )
        )
        return {"errors": errors, "warnings": warnings}

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            errors.append(_issue("node_invalid", f"Node {node_id} is not an object.", node_id=str(node_id)))
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            errors.append(
                _issue(
                    "node_missing_class",
                    f"Node {node_id} has no class_type.",
                    node_id=str(node_id),
                )
            )
        if not isinstance(node.get("inputs"), dict):
            errors.append(
                _issue(
                    "node_missing_inputs",
                    f"Node {node_id} has no inputs object.",
                    node_id=str(node_id),
                    class_type=class_type if isinstance(class_type, str) else None,
                )
            )

    return {"errors": errors, "warnings": warnings}


def validate_mappings(workflow: dict, node_mapping: Any) -> dict:
    """Validate Orange's curated semantic mappings against the workflow graph."""
    errors = []
    warnings = []

    if node_mapping is None:
        node_mapping = {}
    if not isinstance(node_mapping, dict):
        errors.append(_issue("mapping_invalid", "nodeMapping must be an object."))
        return {"errors": errors, "warnings": warnings}

    for mapping_name, mapping in node_mapping.items():
        if not isinstance(mapping, dict):
            errors.append(
                _issue(
                    "mapping_invalid",
                    f"Mapping '{mapping_name}' must be an object.",
                    mapping=mapping_name,
                )
            )
            continue

        node_id = str(mapping.get("nodeId", "")).strip()
        field = str(mapping.get("field", "")).strip()
        if not node_id or not field:
            errors.append(
                _issue(
                    "mapping_incomplete",
                    f"Mapping '{mapping_name}' needs both a node ID and field name.",
                    mapping=mapping_name,
                    node_id=node_id or None,
                    field=field or None,
                )
            )
            continue

        node = workflow.get(node_id)
        if not isinstance(node, dict):
            errors.append(
                _issue(
                    "mapping_node_missing",
                    f"Mapping '{mapping_name}' points to missing node {node_id}.",
                    mapping=mapping_name,
                    node_id=node_id,
                    field=field,
                )
            )
            continue

        inputs = node.get("inputs")
        if isinstance(inputs, dict) and field not in inputs:
            # Orange can inject a valid field even when the exported workflow omitted it,
            # so backend /object_info decides whether this is truly an error.
            warnings.append(
                _issue(
                    "mapping_field_not_in_workflow",
                    f"Mapping '{mapping_name}' field '{field}' is not present in the exported workflow; backend metadata will be checked.",
                    mapping=mapping_name,
                    node_id=node_id,
                    class_type=node.get("class_type"),
                    field=field,
                )
            )

    return {"errors": errors, "warnings": warnings}


def _input_sections(node_def: dict) -> tuple[dict, dict, dict] | None:
    input_info = node_def.get("input")
    if not isinstance(input_info, dict):
        return None

    sections = []
    for name in ("required", "optional", "hidden"):
        value = input_info.get(name, {})
        sections.append(value if isinstance(value, dict) else {})
    return tuple(sections)


def _enum_options(spec: Any) -> list | None:
    if not isinstance(spec, (list, tuple)) or not spec:
        return None
    options = spec[0]
    if isinstance(options, list):
        return options
    return None


def validate_backend(workflow: dict, node_mapping: dict, object_info: Any) -> dict:
    """Compare one API workflow with one ComfyUI server's /object_info response."""
    errors = []
    warnings = []

    if not isinstance(object_info, dict):
        return {
            "errors": [_issue("object_info_invalid", "ComfyUI returned invalid /object_info data.")],
            "warnings": warnings,
        }

    mapped_fields_by_node = defaultdict(set)
    for mapping in (node_mapping or {}).values():
        if isinstance(mapping, dict):
            node_id = str(mapping.get("nodeId", "")).strip()
            field = str(mapping.get("field", "")).strip()
            if node_id and field:
                mapped_fields_by_node[node_id].add(field)

    missing_classes = set()

    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            continue

        node_def = object_info.get(class_type)
        if not isinstance(node_def, dict):
            if class_type not in missing_classes:
                errors.append(
                    _issue(
                        "node_class_missing",
                        f"Missing node class: {class_type}",
                        class_type=class_type,
                    )
                )
                missing_classes.add(class_type)
            continue

        sections = _input_sections(node_def)
        if sections is None:
            warnings.append(
                _issue(
                    "node_metadata_incomplete",
                    f"{class_type} is installed, but its input metadata is incomplete; field validation was skipped.",
                    node_id=str(node_id),
                    class_type=class_type,
                )
            )
            continue

        required, optional, hidden = sections
        available_fields = set(required) | set(optional) | set(hidden)
        node_inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}

        for field in mapped_fields_by_node.get(str(node_id), set()):
            if field not in available_fields:
                errors.append(
                    _issue(
                        "mapped_field_missing",
                        f"Node {node_id} ({class_type}) does not expose mapped field '{field}'.",
                        node_id=str(node_id),
                        class_type=class_type,
                        field=field,
                    )
                )

        for required_field in required:
            if required_field not in node_inputs and required_field not in mapped_fields_by_node.get(str(node_id), set()):
                errors.append(
                    _issue(
                        "required_input_missing",
                        f"Node {node_id} ({class_type}) is missing required input '{required_field}'.",
                        node_id=str(node_id),
                        class_type=class_type,
                        field=required_field,
                    )
                )

        for field, value in node_inputs.items():
            spec = required.get(field)
            if spec is None:
                spec = optional.get(field)
            options = _enum_options(spec)
            if options is None or isinstance(value, list):
                continue
            if value not in options:
                warnings.append(
                    _issue(
                        "value_unavailable",
                        f"Node {node_id} ({class_type}) uses '{value}' for '{field}', but that value is not available on this backend.",
                        node_id=str(node_id),
                        class_type=class_type,
                        field=field,
                        value=value,
                    )
                )

    return {"errors": errors, "warnings": warnings}


async def _check_backend(client: httpx.AsyncClient, server: dict, workflow: dict, node_mapping: dict) -> dict:
    url = str(server.get("url", "")).strip().rstrip("/")
    priority = server.get("priority", 1)
    result = {
        "url": url,
        "priority": priority,
        "reachable": False,
        "status": "offline",
        "errors": [],
        "warnings": [],
        "available_node_classes": None,
        "latency_ms": None,
    }

    if not url:
        result["errors"].append(_issue("backend_url_missing", "Backend URL is empty."))
        return result

    started = time.perf_counter()
    try:
        response = await client.get(f"{url}/object_info")
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        object_info = response.json()
        if not isinstance(object_info, dict):
            raise ValueError("/object_info response was not an object")
    except (httpx.HTTPError, ValueError) as exc:
        result["errors"].append(_issue("backend_unreachable", f"Could not read /object_info: {exc}"))
        return result

    result["reachable"] = True
    result["available_node_classes"] = len(object_info)
    validation = validate_backend(workflow, node_mapping, object_info)
    result["errors"] = validation["errors"]
    result["warnings"] = validation["warnings"]
    if result["errors"]:
        result["status"] = "error"
    elif result["warnings"]:
        result["status"] = "warning"
    else:
        result["status"] = "ready"
    return result


async def run_preflight(workflow_file: str, workflow: dict, node_mapping: dict, servers: list[dict]) -> dict:
    structure = validate_workflow_structure(workflow)
    mappings = validate_mappings(workflow, node_mapping)
    local_errors = structure["errors"] + mappings["errors"]
    local_warnings = structure["warnings"] + mappings["warnings"]

    backend_results = []
    if not local_errors and servers:
        timeout = httpx.Timeout(12.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            backend_results = await asyncio.gather(
                *(_check_backend(client, server, workflow, node_mapping) for server in servers)
            )

    compatible_backends = sum(1 for backend in backend_results if backend["reachable"] and not backend["errors"])
    total_backends = len(servers)

    if local_errors:
        overall_status = "error"
    elif total_backends == 0:
        overall_status = "warning"
        local_warnings.append(_issue("no_backends", "No ComfyUI backends are configured."))
    elif compatible_backends == 0:
        overall_status = "error"
    elif any(backend["status"] != "ready" for backend in backend_results) or local_warnings:
        overall_status = "warning"
    else:
        overall_status = "ready"

    return {
        "workflow": {
            "file": workflow_file,
            "node_count": len(workflow) if isinstance(workflow, dict) else 0,
            "class_count": len(
                {
                    node.get("class_type")
                    for node in workflow.values()
                    if isinstance(node, dict) and isinstance(node.get("class_type"), str)
                }
            )
            if isinstance(workflow, dict)
            else 0,
        },
        "local": {"errors": local_errors, "warnings": local_warnings},
        "backends": backend_results,
        "summary": {
            "status": overall_status,
            "compatible_backends": compatible_backends,
            "total_backends": total_backends,
        },
    }
