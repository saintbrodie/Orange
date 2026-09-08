from copy import deepcopy
from typing import Any, Dict


PUBLIC_MAPPING_KEYS = (
    "prompt",
    "image",
    "image2",
    "width",
    "height",
    "seed",
    "outputText",
)


def _public_ratios(value: Any) -> Dict[str, dict]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, dimensions in value.items():
        if not isinstance(name, str) or not isinstance(dimensions, dict):
            continue
        width = dimensions.get("width")
        height = dimensions.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            result[name] = {"width": width, "height": height}
    return result


def _public_tool(tool: Any) -> dict:
    if not isinstance(tool, dict):
        return {}

    mapping = tool.get("nodeMapping") if isinstance(tool.get("nodeMapping"), dict) else {}
    public_mapping = {
        key: deepcopy(mapping[key])
        for key in PUBLIC_MAPPING_KEYS
        if key in mapping and isinstance(mapping[key], dict)
    }

    result = {
        "id": tool.get("id"),
        "name": tool.get("name"),
        "outputType": tool.get("outputType", "image"),
        "nodeMapping": public_mapping,
    }

    ratios = _public_ratios(tool.get("aspectRatios"))
    if ratios:
        result["aspectRatios"] = ratios

    prompt_enhance = tool.get("promptEnhance")
    if isinstance(prompt_enhance, dict):
        result["promptEnhance"] = {"enabled": prompt_enhance.get("enabled", True) is not False}

    return result


def build_public_config(config: Any) -> dict:
    source = config if isinstance(config, dict) else {}
    tools = []
    for tool in source.get("tools", []):
        public_tool = _public_tool(tool)
        if public_tool.get("id") and public_tool.get("name"):
            tools.append(public_tool)

    result = {
        "tools": tools,
        "aspectRatios": _public_ratios(source.get("aspectRatios")),
        "llmEnabled": bool(source.get("llm", {}).get("enabled", False))
        if isinstance(source.get("llm"), dict)
        else False,
    }

    modify_tool = source.get("modifyTool")
    public_ids = {tool["id"] for tool in tools}
    if isinstance(modify_tool, str) and modify_tool in public_ids:
        result["modifyTool"] = modify_tool

    return result
