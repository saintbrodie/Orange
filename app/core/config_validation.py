import json
import os
import re
from typing import Any
from urllib.parse import urlparse

from app.core.preflight import validate_mappings, validate_workflow_structure

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WORKFLOWS_DIR = os.path.join(PROJECT_ROOT, "workflows")
DEFAULT_WORKFLOWS_DIR = os.path.join(WORKFLOWS_DIR, "defaults")

TOOL_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
ALLOWED_MAPPING_KEYS = {"prompt", "image", "image2", "width", "height", "seed", "outputText"}
ALLOWED_OUTPUT_TYPES = {"image", "video", "audio", "text"}
ALLOWED_LLM_PROVIDERS = {"openai", "ollama", "gemini", "anthropic"}


def _issue(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _resolve_workflow_file(filename: str) -> str | None:
    for directory in (WORKFLOWS_DIR, DEFAULT_WORKFLOWS_DIR):
        candidate = os.path.join(directory, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def _validate_aspect_ratios(value: Any, path: str, errors: list[dict]) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errors.append(_issue(path, "aspect_ratios_invalid", "Aspect ratios must be an object."))
        return

    for ratio_name, dimensions in value.items():
        ratio_path = f"{path}.{ratio_name}"
        if not isinstance(ratio_name, str) or not ratio_name.strip():
            errors.append(_issue(path, "aspect_ratio_name_invalid", "Aspect ratio names must be non-empty strings."))
            continue
        if not isinstance(dimensions, dict):
            errors.append(_issue(ratio_path, "aspect_ratio_invalid", "Aspect ratio dimensions must be an object."))
            continue
        for dimension in ("width", "height"):
            raw = dimensions.get(dimension)
            if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
                errors.append(
                    _issue(
                        f"{ratio_path}.{dimension}",
                        "dimension_invalid",
                        f"{dimension.capitalize()} must be a positive integer.",
                    )
                )


def validate_config(config: Any) -> dict:
    """Validate Orange's small semantic configuration contract.

    This intentionally validates only decisions Orange owns. ComfyUI-specific model,
    sampler, node implementation, and dependency checks remain the job of preflight.
    """
    errors: list[dict] = []
    warnings: list[dict] = []

    if not isinstance(config, dict):
        return {
            "errors": [_issue("config", "config_invalid", "Configuration must be a JSON object.")],
            "warnings": warnings,
        }

    admin_key = config.get("adminKey")
    if admin_key is not None and (not isinstance(admin_key, str) or not admin_key):
        errors.append(_issue("adminKey", "admin_key_invalid", "Admin key must be a non-empty string."))

    servers = config.get("comfyServers", [])
    if not isinstance(servers, list):
        errors.append(_issue("comfyServers", "servers_invalid", "comfyServers must be a list."))
        servers = []
    elif not servers:
        warnings.append(
            _issue(
                "comfyServers",
                "servers_empty",
                "No explicit ComfyUI servers are configured; Orange will use its legacy localhost fallback.",
            )
        )

    seen_urls = set()
    for index, server in enumerate(servers):
        path = f"comfyServers[{index}]"
        if not isinstance(server, dict):
            errors.append(_issue(path, "server_invalid", "Each ComfyUI server must be an object."))
            continue
        url = server.get("url")
        if not _is_http_url(url):
            errors.append(_issue(f"{path}.url", "server_url_invalid", "Server URL must be a valid http:// or https:// URL."))
        else:
            normalized = url.strip().rstrip("/")
            if normalized in seen_urls:
                errors.append(_issue(f"{path}.url", "server_url_duplicate", "Duplicate ComfyUI server URL."))
            seen_urls.add(normalized)

        priority = server.get("priority", 1)
        if isinstance(priority, bool):
            errors.append(_issue(f"{path}.priority", "priority_invalid", "Priority must be a positive integer."))
        else:
            try:
                parsed_priority = int(priority)
            except (TypeError, ValueError):
                parsed_priority = 0
            if parsed_priority < 1:
                errors.append(_issue(f"{path}.priority", "priority_invalid", "Priority must be a positive integer."))

    legacy_url = config.get("comfyServerUrl")
    if legacy_url is not None and not _is_http_url(legacy_url):
        errors.append(_issue("comfyServerUrl", "server_url_invalid", "Legacy server URL must be a valid http:// or https:// URL."))

    _validate_aspect_ratios(config.get("aspectRatios"), "aspectRatios", errors)

    target_mp = config.get("targetMegapixels")
    if target_mp is not None:
        try:
            if float(target_mp) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(_issue("targetMegapixels", "target_mp_invalid", "Target megapixels must be greater than zero."))

    llm = config.get("llm")
    if llm is not None:
        if not isinstance(llm, dict):
            errors.append(_issue("llm", "llm_invalid", "LLM settings must be an object."))
        else:
            provider = llm.get("provider")
            if provider and provider not in ALLOWED_LLM_PROVIDERS:
                errors.append(
                    _issue(
                        "llm.provider",
                        "llm_provider_invalid",
                        f"LLM provider must be one of: {', '.join(sorted(ALLOWED_LLM_PROVIDERS))}.",
                    )
                )
            base_url = llm.get("baseUrl")
            if base_url and not _is_http_url(base_url):
                errors.append(_issue("llm.baseUrl", "llm_url_invalid", "LLM base URL must be a valid http:// or https:// URL."))
            if llm.get("enabled") and not str(llm.get("model", "")).strip():
                warnings.append(_issue("llm.model", "llm_model_missing", "Prompt enhancement is enabled but no model is selected."))

    tools = config.get("tools", [])
    if not isinstance(tools, list):
        errors.append(_issue("tools", "tools_invalid", "tools must be a list."))
        tools = []

    seen_tool_ids = set()
    tools_by_id = {}

    for index, tool in enumerate(tools):
        path = f"tools[{index}]"
        if not isinstance(tool, dict):
            errors.append(_issue(path, "tool_invalid", "Each tool must be an object."))
            continue

        tool_id = tool.get("id")
        if not isinstance(tool_id, str) or not TOOL_ID_RE.fullmatch(tool_id):
            errors.append(
                _issue(
                    f"{path}.id",
                    "tool_id_invalid",
                    "Tool ID must contain only letters, numbers, underscores, or hyphens.",
                )
            )
        elif tool_id in seen_tool_ids:
            errors.append(_issue(f"{path}.id", "tool_id_duplicate", f"Duplicate tool ID '{tool_id}'."))
        else:
            seen_tool_ids.add(tool_id)
            tools_by_id[tool_id] = tool

        name = tool.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(_issue(f"{path}.name", "tool_name_invalid", "Tool display name must be a non-empty string."))

        output_type = tool.get("outputType", "image")
        if output_type not in ALLOWED_OUTPUT_TYPES:
            errors.append(
                _issue(
                    f"{path}.outputType",
                    "output_type_invalid",
                    f"Output type must be one of: {', '.join(sorted(ALLOWED_OUTPUT_TYPES))}.",
                )
            )

        workflow_file = tool.get("workflowFile")
        workflow_path = None
        if not isinstance(workflow_file, str) or not workflow_file.lower().endswith(".json"):
            errors.append(_issue(f"{path}.workflowFile", "workflow_file_invalid", "Workflow file must be a .json filename."))
        elif os.path.basename(workflow_file) != workflow_file:
            errors.append(_issue(f"{path}.workflowFile", "workflow_path_invalid", "Workflow files must live directly inside Orange's workflows folder."))
        else:
            workflow_path = _resolve_workflow_file(workflow_file)
            if workflow_path is None:
                errors.append(_issue(f"{path}.workflowFile", "workflow_file_missing", f"Workflow file '{workflow_file}' was not found."))

        mapping = tool.get("nodeMapping", {})
        if not isinstance(mapping, dict):
            errors.append(_issue(f"{path}.nodeMapping", "mapping_invalid", "nodeMapping must be an object."))
            mapping = {}
        else:
            unknown_mapping_keys = sorted(set(mapping) - ALLOWED_MAPPING_KEYS)
            for key in unknown_mapping_keys:
                errors.append(
                    _issue(
                        f"{path}.nodeMapping.{key}",
                        "mapping_type_unknown",
                        f"'{key}' is not a supported Orange mapping type.",
                    )
                )

            if ("width" in mapping) != ("height" in mapping):
                errors.append(
                    _issue(
                        f"{path}.nodeMapping",
                        "resolution_mapping_incomplete",
                        "Width and height mappings must be configured together.",
                    )
                )

            for mapping_name, mapping_value in mapping.items():
                mapping_path = f"{path}.nodeMapping.{mapping_name}"
                if not isinstance(mapping_value, dict):
                    errors.append(_issue(mapping_path, "mapping_invalid", "Mapping must be an object."))
                    continue
                node_id = mapping_value.get("nodeId")
                field = mapping_value.get("field")
                if not isinstance(node_id, str) or not node_id.strip():
                    errors.append(_issue(f"{mapping_path}.nodeId", "mapping_node_invalid", "Mapping nodeId must be a non-empty string."))
                if not isinstance(field, str) or not field.strip():
                    errors.append(_issue(f"{mapping_path}.field", "mapping_field_invalid", "Mapping field must be a non-empty string."))
                if mapping_name == "seed" and "generateRandom" in mapping_value and not isinstance(mapping_value.get("generateRandom"), bool):
                    errors.append(_issue(f"{mapping_path}.generateRandom", "seed_random_invalid", "generateRandom must be true or false."))

        _validate_aspect_ratios(tool.get("aspectRatios"), f"{path}.aspectRatios", errors)

        if workflow_path and isinstance(mapping, dict):
            try:
                with open(workflow_path, "r", encoding="utf-8") as handle:
                    workflow = json.load(handle)
                structure = validate_workflow_structure(workflow)
                local_mapping = validate_mappings(workflow, mapping)
                for issue in structure["errors"] + local_mapping["errors"]:
                    errors.append(
                        _issue(
                            f"{path}.nodeMapping",
                            issue.get("code", "workflow_invalid"),
                            issue.get("message", "Workflow validation failed."),
                        )
                    )
                for issue in structure["warnings"] + local_mapping["warnings"]:
                    warnings.append(
                        _issue(
                            f"{path}.nodeMapping",
                            issue.get("code", "workflow_warning"),
                            issue.get("message", "Workflow validation warning."),
                        )
                    )
            except (OSError, ValueError) as exc:
                errors.append(_issue(f"{path}.workflowFile", "workflow_json_invalid", f"Could not read workflow JSON: {exc}"))

    modify_tool = config.get("modifyTool")
    if modify_tool:
        if modify_tool not in tools_by_id:
            errors.append(_issue("modifyTool", "modify_tool_missing", f"Modify tool '{modify_tool}' does not exist."))
        elif not tools_by_id[modify_tool].get("nodeMapping", {}).get("image"):
            errors.append(_issue("modifyTool", "modify_tool_no_image", "Modify tool must expose Orange's image mapping."))

    return {"errors": errors, "warnings": warnings}
