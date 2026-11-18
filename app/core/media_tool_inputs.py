"""Public controls for API tools without exposing provider configuration."""
from copy import deepcopy
from app.core.media_providers import validate_api_tool


def public_api_inputs(tool):
    model = validate_api_tool(tool)
    inputs = tool["api"]
    source_aspect = model.source_aspect or (model.reference_aspect and bool(inputs.get('references')))
    # Truthy semantic markers retain compatibility with Generate's control checks.
    mapping = {"prompt": {"enabled": True}}
    if not source_aspect:
        mapping.update(width={"enabled": True}, height={"enabled": True})
    if inputs.get("requireImage"):
        mapping["image"] = {"enabled": True}
    ratios = {}
    for ratio in inputs["ratios"]:
        if source_aspect:
            continue
        width, height = (int(value) for value in ratio.split(":"))
        if tool["provider"] == "openai":
            width, height = {"1:1": (1024, 1024), "3:2": (1536, 1024), "2:3": (1024, 1536)}[ratio]
        else:
            factor = 1024 / max(width, height)
            width, height = round(width * factor), round(height * factor)
        ratios[ratio] = {"width": width, "height": height}
    result = {"provider": tool["provider"], "nodeMapping": mapping, "aspectRatios": ratios,
              "firstFrame": bool(inputs.get("references")) and not inputs.get("requireImage", False),
              "optionalReference": inputs.get("references", 0) > 1,
              "resolution": {"options": deepcopy(inputs["resolutions"]), "default": inputs["defaultResolution"]}}
    if model.output == "video":
        result["duration"] = {"options": deepcopy(inputs["durations"]), "default": inputs["defaultDuration"]}
    return result
