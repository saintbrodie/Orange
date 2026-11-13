"""Optional media inputs shared by submission, installation, and verification."""
import math


def tool_variants(tool):
    variants = [tool]
    for key, suffix, label in (("imageVariant", "first-frame", "first frame"),
                               ("referenceVariant", "reference", "with reference")):
        if isinstance(tool.get(key), dict):
            variant = {**tool, **tool[key]}
            variant.pop("imageVariant", None)
            variant.pop("referenceVariant", None)
            variant["id"] = str(tool.get("id", "")) + "-" + suffix
            variant["name"] = str(tool.get("name", "")) + " (" + label + ")"
            variants.append(variant)
    return variants


def select_input_variant(tool, has_image, has_image2=False):
    if has_image2 and isinstance(tool.get("referenceVariant"), dict):
        return next(v for v in tool_variants(tool)[1:] if v["id"].endswith("-reference"))
    if has_image and isinstance(tool.get("imageVariant"), dict):
        return tool_variants(tool)[1]
    return tool


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
