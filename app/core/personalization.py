import json
import os
import re
from copy import deepcopy

from app.core.config import PROJECT_ROOT

PERSONALIZATION_PATH = os.path.join(PROJECT_ROOT, "workflows", "personalization.json")
BRANDING_DIR = os.path.join(PROJECT_ROOT, "workflows", "branding")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
THEME_LOGO_DIR = os.path.join(STATIC_DIR, "theme-assets", "logos")
THEME_IDS = {"classic", "cyber", "princess", "arcade", "adventure", "midnight", "custom"}
LEGACY_THEME_ALIASES = {"botanical": "adventure"}
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

DEFAULT_PERSONALIZATION = {
    "theme": "classic",
    "branding": {
        "appName": "Orange",
        "tagline": "AI Media Tools",
        "footerText": "",
    },
    "custom": {
        "accent": "#f97316",
        "accentSecondary": "#ea580c",
        "background": "#09090b",
        "panel": "#18181b",
        "text": "#f4f4f5",
        "muted": "#71717a",
        "radius": 24,
        "motion": "normal",
    },
}


def _normalize_theme_id(theme: str | None) -> str:
    normalized = str(theme or "classic").strip().lower()
    return LEGACY_THEME_ALIASES.get(normalized, normalized)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_personalization() -> dict:
    try:
        with open(PERSONALIZATION_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            result = _deep_merge(DEFAULT_PERSONALIZATION, data)
            result["theme"] = _normalize_theme_id(result.get("theme"))
            return result
    except (OSError, json.JSONDecodeError):
        pass
    return deepcopy(DEFAULT_PERSONALIZATION)


def validate_personalization(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Personalization settings must be an object.")

    theme = _normalize_theme_id(data.get("theme", "classic"))
    if theme not in THEME_IDS:
        raise ValueError(f"Unknown theme '{theme}'.")

    branding = data.get("branding", {})
    if not isinstance(branding, dict):
        raise ValueError("Branding settings must be an object.")

    app_name = str(branding.get("appName", "Orange")).strip()
    tagline = str(branding.get("tagline", "AI Media Tools")).strip()
    footer = str(branding.get("footerText", "")).strip()
    if not app_name or len(app_name) > 64:
        raise ValueError("App name must be between 1 and 64 characters.")
    if len(tagline) > 120:
        raise ValueError("Tagline must be 120 characters or fewer.")
    if len(footer) > 160:
        raise ValueError("Footer text must be 160 characters or fewer.")

    custom = data.get("custom", {})
    if not isinstance(custom, dict):
        raise ValueError("Custom theme settings must be an object.")

    normalized_custom = deepcopy(DEFAULT_PERSONALIZATION["custom"])
    for key in ("accent", "accentSecondary", "background", "panel", "text", "muted"):
        value = str(custom.get(key, normalized_custom[key])).strip()
        if not HEX_COLOR_RE.fullmatch(value):
            raise ValueError(f"{key} must be a six-digit hex color such as #f97316.")
        normalized_custom[key] = value.lower()

    try:
        radius = int(custom.get("radius", normalized_custom["radius"]))
    except (TypeError, ValueError):
        raise ValueError("Corner radius must be a whole number.")
    if radius < 0 or radius > 40:
        raise ValueError("Corner radius must be between 0 and 40 pixels.")
    normalized_custom["radius"] = radius

    motion = str(custom.get("motion", normalized_custom["motion"])).strip().lower()
    if motion not in {"reduced", "normal", "playful"}:
        raise ValueError("Motion must be reduced, normal, or playful.")
    normalized_custom["motion"] = motion

    return {
        "theme": theme,
        "branding": {
            "appName": app_name,
            "tagline": tagline,
            "footerText": footer,
        },
        "custom": normalized_custom,
    }


def save_personalization(data: dict) -> dict:
    normalized = validate_personalization(data)
    os.makedirs(os.path.dirname(PERSONALIZATION_PATH), exist_ok=True)
    tmp_path = PERSONALIZATION_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, PERSONALIZATION_PATH)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    return normalized


def branding_path(kind: str) -> str | None:
    if kind not in {"logo", "icon"}:
        return None
    if not os.path.isdir(BRANDING_DIR):
        return None
    for extension in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = os.path.join(BRANDING_DIR, kind + extension)
        if os.path.isfile(candidate):
            return candidate
    return None


def clear_branding(kind: str) -> None:
    if kind not in {"logo", "icon"}:
        raise ValueError("Branding kind must be logo or icon.")
    if not os.path.isdir(BRANDING_DIR):
        return
    for extension in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = os.path.join(BRANDING_DIR, kind + extension)
        if os.path.isfile(candidate):
            os.remove(candidate)


def theme_logo_path(theme: str, kind: str) -> str:
    """Return the editable SVG file used for a preset mascot."""
    if kind not in {"full", "head"}:
        raise ValueError("Mascot kind must be full or head.")

    normalized_theme = _normalize_theme_id(theme)
    if normalized_theme == "custom":
        normalized_theme = "classic"
    if normalized_theme not in THEME_IDS:
        raise ValueError("Unknown theme.")

    path = os.path.join(THEME_LOGO_DIR, f"{normalized_theme}-{kind}.svg")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


def render_theme_svg(theme: str, kind: str) -> str:
    """Compatibility helper: load the editable preset SVG from disk."""
    with open(theme_logo_path(theme, kind), "r", encoding="utf-8") as handle:
        return handle.read()
