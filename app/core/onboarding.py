import json
import os

from app.core.config import PROJECT_ROOT, USER_CONFIG_PATH

SETUP_STATE_PATH = os.path.join(PROJECT_ROOT, "workflows", "setup-state.json")


def detect_install_mode() -> str:
    return os.environ.get("ORANGE_INSTALL_MODE", "manual").strip().lower() or "manual"


def managed_comfy_dir() -> str | None:
    path = os.environ.get("ORANGE_COMFYUI_DIR", "").strip()
    if path and os.path.isdir(path):
        return os.path.abspath(path)
    return None


def managed_models_root() -> str | None:
    explicit = os.environ.get("ORANGE_MODELS_ROOT", "").strip()
    if explicit and os.path.isdir(explicit):
        return os.path.abspath(explicit)
    comfy_dir = managed_comfy_dir()
    if comfy_dir:
        candidate = os.path.join(comfy_dir, "models")
        if os.path.isdir(candidate):
            return os.path.abspath(candidate)
    return None


def initialize_setup_state(was_fresh_install: bool) -> None:
    if os.path.exists(SETUP_STATE_PATH):
        return
    os.makedirs(os.path.dirname(SETUP_STATE_PATH), exist_ok=True)
    state = {
        "complete": not was_fresh_install,
        "migratedExistingInstall": not was_fresh_install,
        "installMode": detect_install_mode(),
    }
    _write_state(state)


def load_setup_state() -> dict:
    if not os.path.exists(SETUP_STATE_PATH):
        # Existing installs upgrading from versions before onboarding should not
        # suddenly be forced through a first-run wizard.
        return {
            "complete": os.path.exists(USER_CONFIG_PATH),
            "migratedExistingInstall": os.path.exists(USER_CONFIG_PATH),
            "installMode": detect_install_mode(),
        }
    try:
        with open(SETUP_STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        state = {}
    state.setdefault("complete", False)
    state["installMode"] = detect_install_mode()
    return state


def setup_required() -> bool:
    return not bool(load_setup_state().get("complete"))


def mark_setup_complete() -> None:
    state = load_setup_state()
    state["complete"] = True
    state["installMode"] = detect_install_mode()
    _write_state(state)


def _write_state(state: dict) -> None:
    os.makedirs(os.path.dirname(SETUP_STATE_PATH), exist_ok=True)
    tmp = SETUP_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SETUP_STATE_PATH)
