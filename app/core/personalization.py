import json
import os
import re
from copy import deepcopy

from app.core.config import PROJECT_ROOT

PERSONALIZATION_PATH = os.path.join(PROJECT_ROOT, "workflows", "personalization.json")
BRANDING_DIR = os.path.join(PROJECT_ROOT, "workflows", "branding")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
THEME_IDS = {"classic", "cyber", "princess", "arcade", "botanical", "midnight", "custom"}
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

# Themed mascot rendering deliberately reuses Orange's original vector geometry.
# Only palette tokens and small decorative overlays change, so every preset stays
# recognizably the same mascot and automatically follows future geometry updates.
BASE_SVG_COLORS = ["#77310a", "#13171f", "#f67a04", "#625649", "#9f978b", "#fcbd67", "#ea5205", "#fdfdfd"]
THEME_SVG_PALETTES = {
    # Cyber is intentionally monochrome phosphor-terminal green now. No cyan,
    # magenta, or warm Orange colors should survive into the mascot itself.
    "cyber": ["#17351f", "#020604", "#3fa85b", "#23452c", "#668d6e", "#9ddaaa", "#79ff8e", "#e2f7e5"],
    "princess": ["#6b214f", "#2a1228", "#f472b6", "#8f5d83", "#d8a8cc", "#fde1f1", "#c084fc", "#fff7fb"],
    # Arcade mirrors the synthwave UI but keeps enough tonal separation that the
    # canonical cat face remains readable at small sidebar sizes.
    "arcade": ["#3f165c", "#10051b", "#ec4899", "#5b2b72", "#8b5cf6", "#67e8f9", "#00e5ff", "#fff4ff"],
    # Outdoors palette inspired by the supplied mountain reference: cool blue-
    # grays, stone, muted teal and a restrained rust trail-marker accent.
    "botanical": ["#394b50", "#202c30", "#647c7c", "#51646b", "#9dabc7", "#b8a6a0", "#c57a3c", "#eef1ef"],
    "midnight": ["#111827", "#030712", "#172554", "#334155", "#64748b", "#8ea6c9", "#d6b76b", "#f8fafc"],
}


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
            return _deep_merge(DEFAULT_PERSONALIZATION, data)
    except (OSError, json.JSONDecodeError):
        pass
    return deepcopy(DEFAULT_PERSONALIZATION)


def validate_personalization(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Personalization settings must be an object.")

    theme = str(data.get("theme", "classic")).strip().lower()
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


def _decoration(theme: str, kind: str) -> str:
    head = kind == "head"
    if theme == "cyber":
        # A simple phosphor visor reads as retro terminal hardware without
        # dragging the mascot back toward cyan/magenta sci-fi.
        return (
            '<style>@keyframes orangeCyberScan{0%,100%{opacity:.35}50%{opacity:.8}}</style>'
            + (
                '<g><rect x="91" y="211" width="255" height="64" rx="16" fill="#020604" fill-opacity=".88" stroke="#79ff8e" stroke-width="5"/><path d="M111 240h211" stroke="#79ff8e" stroke-width="3" stroke-dasharray="8 10" opacity=".55" style="animation:orangeCyberScan 2.4s ease-in-out infinite"/></g>'
                if head
                else '<g><rect x="273" y="214" width="318" height="77" rx="18" fill="#020604" fill-opacity=".88" stroke="#79ff8e" stroke-width="7"/><path d="M300 250h264" stroke="#79ff8e" stroke-width="4" stroke-dasharray="10 12" opacity=".55" style="animation:orangeCyberScan 2.4s ease-in-out infinite"/></g>'
            )
        )
    if theme == "princess":
        return (
            '<style>@keyframes orangeTwinkle{0%,100%{opacity:.25}50%{opacity:1}}</style>'
            + ('<g><path d="M157 75l23-42 39 48 38-55 35 50 28-35 10 70H145z" fill="#faccf4" stroke="#f472b6" stroke-width="5"/><circle cx="181" cy="81" r="6" fill="#fff"/><circle cx="219" cy="82" r="7" fill="#c084fc"/><circle cx="258" cy="80" r="6" fill="#fff"/><path d="M371 145l7 17 17 7-17 7-7 17-7-17-17-7 17-7z" fill="#fff1f7" style="animation:orangeTwinkle 1.7s ease-in-out infinite"/></g>' if head else '<g><path d="M315 82l38-52 48 58 50-67 48 64 42-47 14 84H300z" fill="#faccf4" stroke="#f472b6" stroke-width="7"/><circle cx="354" cy="89" r="9" fill="#fff"/><circle cx="402" cy="92" r="10" fill="#c084fc"/><circle cx="458" cy="88" r="9" fill="#fff"/><path d="M610 155l9 22 22 9-22 9-9 22-9-22-22-9 22-9z" fill="#fff1f7" style="animation:orangeTwinkle 1.7s ease-in-out infinite"/></g>')
        )
    if theme == "arcade":
        # Keep the 80s costume legible at tiny logo sizes: three ideas only —
        # mullet, aviator shades, and a simple cyan/magenta windbreaker.
        if head:
            return (
                '<style>@keyframes orangeArcadeGlint{0%,82%,100%{opacity:.15}88%{opacity:.9}}</style>'
                '<g>'
                '<path d="M116 142c20-52 57-75 101-72 42-17 87-2 111 35 18 27 21 61 10 94l-25-28 8 53-29-37-6-55c-42-23-91-22-133 2l-12 62-27 33 7-50-24 24c-5-22 1-43 19-61z" fill="#3f165c" stroke="#ec4899" stroke-width="5" stroke-linejoin="round"/>'
                '<g fill="#10051b" stroke="#00e5ff" stroke-width="5"><rect x="105" y="205" width="101" height="55" rx="17"/><rect x="231" y="205" width="101" height="55" rx="17"/></g>'
                '<path d="M206 223h25" stroke="#ec4899" stroke-width="6" stroke-linecap="round"/>'
                '<path d="M124 219l58 15M250 219l58 15" stroke="#fff4ff" stroke-width="4" opacity=".5" style="animation:orangeArcadeGlint 3.2s steps(1,end) infinite"/>'
                '</g>'
            )
        return (
            '<style>@keyframes orangeArcadeGlint{0%,82%,100%{opacity:.15}88%{opacity:.9}}</style>'
            '<g>'
            '<path d="M300 146c28-65 76-92 131-85 56-17 111 6 137 56 17 33 17 72 2 109l-31-35 8 64-35-45-7-69c-54-29-116-28-169 3l-15 74-34 42 9-61-30 29c-5-27 6-55 34-82z" fill="#3f165c" stroke="#ec4899" stroke-width="8" stroke-linejoin="round"/>'
            '<g fill="#10051b" stroke="#00e5ff" stroke-width="8"><rect x="286" y="211" width="137" height="71" rx="22"/><rect x="443" y="211" width="137" height="71" rx="22"/></g>'
            '<path d="M423 235h20" stroke="#ec4899" stroke-width="9" stroke-linecap="round"/>'
            '<path d="M312 228l78 20M469 228l78 20" stroke="#fff4ff" stroke-width="6" opacity=".5" style="animation:orangeArcadeGlint 3.2s steps(1,end) infinite"/>'
            '<path d="M200 625l118-67 84 41 84-41 118 67 54 198-111 47-64-183-81 67-81-67-64 183-111-47z" fill="#5b2b72" stroke="#10051b" stroke-width="8" stroke-linejoin="round"/>'
            '<path d="M202 626l116-68 84 41-81 88-127 45z" fill="#00e5ff"/>'
            '<path d="M602 626l-116-68-84 41 81 88 127 45z" fill="#ec4899"/>'
            '<path d="M321 687l81-88 81 88-81 67z" fill="#8b5cf6"/>'
            '</g>'
        )
    if theme == "botanical":
        # Adventure treatment: a restrained rust trail bandana/neck scarf rather
        # than the previous decorative leaf. The rest comes from the topo palette.
        return (
            '<g>'
            + (
                '<path d="M132 337c52 22 119 22 171 0l-16 38-68 31-69-31z" fill="#c57a3c" stroke="#394b50" stroke-width="4"/><path d="M219 405l28-8-16 16z" fill="#b8a6a0"/>'
                if head
                else '<path d="M310 398c59 27 126 27 185 0l-18 52-75 39-75-39z" fill="#c57a3c" stroke="#394b50" stroke-width="6"/><circle cx="402" cy="445" r="12" fill="#9dabc7" stroke="#394b50" stroke-width="4"/>'
            )
            + '</g>'
        )
    if theme == "midnight":
        return (
            '<style>@keyframes orangeStarTwinkle{0%,100%{opacity:.2}50%{opacity:1}}</style>'
            + ('<g><path d="M344 57c-26 11-40 34-36 60 5 26 26 42 52 42-22 13-51 9-68-12-24-30-14-73 19-91 11-6 22-8 33-7z" fill="#d6b76b"/><path d="M75 105l5 12 12 5-12 5-5 12-5-12-12-5 12-5z" fill="#8ea6c9" style="animation:orangeStarTwinkle 2.6s ease-in-out infinite"/></g>' if head else '<g><path d="M610 80c-34 14-52 44-47 78 7 35 34 56 68 56-28 17-66 12-88-16-31-39-18-95 25-118 14-8 29-10 42-9z" fill="#d6b76b"/><path d="M177 132l6 14 14 6-14 6-6 14-6-14-14-6 14-6z" fill="#8ea6c9" style="animation:orangeStarTwinkle 2.6s ease-in-out infinite"/></g>')
        )
    return ""


def render_theme_svg(theme: str, kind: str) -> str:
    if kind not in {"full", "head"}:
        raise ValueError("Mascot kind must be full or head.")
    normalized_theme = str(theme or "classic").lower()
    if normalized_theme == "custom":
        normalized_theme = "classic"
    if normalized_theme not in THEME_IDS:
        raise ValueError("Unknown theme.")

    filename = "orange.svg" if kind == "full" else "orange-head.svg"
    with open(os.path.join(STATIC_DIR, filename), "r", encoding="utf-8") as handle:
        svg = handle.read()

    palette = THEME_SVG_PALETTES.get(normalized_theme)
    if palette:
        for source, target in zip(BASE_SVG_COLORS, palette):
            svg = svg.replace(source, target)

    decoration = _decoration(normalized_theme, kind)
    if decoration:
        svg = svg.replace("</svg>", decoration + "</svg>")
    return svg
