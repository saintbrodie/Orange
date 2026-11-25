import json
import os
import socket
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "runtime" / "listener.json"
RESTART_PATH = ROOT / "RESTART_REQUIRED"
ACCESS_MODES = ("local", "open-lan", "team")


@dataclass(frozen=True)
class ListenerSettings:
    mode: str
    port: int
    allow_lan_http: bool = False

    def __post_init__(self):
        if self.mode not in ACCESS_MODES:
            raise ValueError("Choose Local, Open LAN, or Team.")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Use a port from 1 to 65535.")
        if type(self.allow_lan_http) is not bool:
            raise ValueError("LAN HTTP must be true or false.")
        if self.mode == "local" and self.allow_lan_http:
            raise ValueError("LAN HTTP must be off in Local mode.")

    @property
    def host(self):
        return "0.0.0.0" if self.mode == "open-lan" or self.allow_lan_http else "127.0.0.1"


def lan_http_requested():
    value = os.environ.get("ORANGE_RUNNING_LAN_HTTP", os.environ.get("ORANGE_ALLOW_LAN_HTTP", ""))
    return value.strip().lower() in {"1", "true", "yes"}


def configured_settings(fallback=None):
    try:
        with SETTINGS_PATH.open(encoding="utf-8") as settings_file:
            settings = json.load(settings_file)
    except FileNotFoundError:
        if fallback is not None:
            return fallback
        mode = os.environ.get("ORANGE_ACCESS_MODE", "local").strip().lower()
        return ListenerSettings(mode, int(os.environ.get("ORANGE_PORT", "7070")), mode != "local" and lan_http_requested())
    return ListenerSettings(settings["mode"], settings["port"], settings.get("allow_lan_http", False))


def load_open_lan_http_from_legacy_launcher():
    port = os.environ.get("ORANGE_RUNNING_PORT")
    if not port or "ORANGE_RUNNING_LAN_HTTP" in os.environ:
        return
    os.environ["ORANGE_RUNNING_LEGACY_LAUNCHER"] = "1"
    settings = configured_settings()
    # Existing Open LAN launchers already bind to all interfaces. The child can
    # read the saved HTTP option once at startup if the launcher predates it.
    if settings.mode == "open-lan" and str(settings.port) == port:
        os.environ["ORANGE_RUNNING_LAN_HTTP"] = "1" if settings.allow_lan_http else "0"


def needs_launcher_relaunch(settings):
    legacy = "ORANGE_RUNNING_LAN_HTTP" not in os.environ or os.environ.get("ORANGE_RUNNING_LEGACY_LAUNCHER") == "1"
    return bool(os.environ.get("ORANGE_RUNNING_PORT") and legacy and settings.mode == "team" and settings.allow_lan_http)


def save_settings(settings):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SETTINGS_PATH.parent, delete=False) as settings_file:
        temporary = Path(settings_file.name)
        try:
            json.dump(asdict(settings), settings_file)
            settings_file.flush()
            os.fsync(settings_file.fileno())
        except BaseException:
            settings_file.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, SETTINGS_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def check_port(settings):
    with socket.socket() as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((settings.host, settings.port))
