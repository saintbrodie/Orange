"""Optional video inputs shared by submission, installation, and verification."""
import math


def tool_variants(tool):
    variants = [tool]
    image_variant = tool.get("imageVariant")
    if isinstance(image_variant, dict):
        variant = {**tool, **image_variant}
        variant.pop("imageVariant", None)
        variant["id"] = str(tool.get("id", "")) + "-first-frame"
        variant["name"] = str(tool.get("name", "")) + " (first frame)"
        variants.append(variant)
    return variants


def select_input_variant(tool, has_image):
    return tool_variants(tool)[-1] if has_image and isinstance(tool.get("imageVariant"), dict) else tool


def apply_duration(workflow, tool, seconds=None):
    settings = tool.get("duration")
    mapping = tool.get("nodeMapping", {}).get("duration")
    if not settings or not mapping:
        if seconds is not None:
            raise ValueError("This tool does not offer a duration control")
        return
    seconds = settings["default"] if seconds is None else seconds
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds not in settings["options"]:
        raise ValueError("Choose one of the supported video lengths")
    frames = int(round(seconds * settings["frameRate"] / settings["frameMultiple"])) * settings["frameMultiple"] + 1
    workflow[mapping["nodeId"]]["inputs"][mapping["field"]] = frames
