import hashlib
import hmac
import os
import re
import secrets
import socket
import sqlite3
import time
from contextlib import closing, contextmanager
from functools import lru_cache
from ipaddress import ip_address, ip_network
from pathlib import Path

from fastapi import HTTPException, Request, Response

from app.core.config import PROJECT_ROOT, load_config
from app.core.listener import ACCESS_MODES, lan_http_requested

GUEST_COOKIE = "orange_guest"
GALLERY_COOKIE = "orange_gallery"
GALLERY_MAX_AGE = 3600
JOB_ACCESS_PATH = Path(PROJECT_ROOT) / "runtime" / "job-access.db"
_GALLERY_KEY = secrets.token_bytes(32)
_GUEST_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_LAN_NETWORKS = tuple(ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10",
))


def access_mode():
    mode = os.environ.get("ORANGE_RUNNING_ACCESS_MODE", os.environ.get("ORANGE_ACCESS_MODE", "local")).strip().lower()
    if mode not in ACCESS_MODES:
        raise ValueError("ORANGE_ACCESS_MODE must be local, open-lan, or team.")
    return mode


def is_open_lan():
    return access_mode() == "open-lan"


def is_team():
    return access_mode() == "team"


def _listed_values(name):
    return {item.strip() for item in os.environ.get(name, "").split(",") if item.strip()}


def _system_fqdn():
    if os.name != "nt":
        return socket.getfqdn()

    from ctypes import byref, create_unicode_buffer, windll
    from ctypes.wintypes import DWORD

    # Windows may return only the short name from socket.getfqdn().
    physical_dns_fully_qualified = 7  # COMPUTER_NAME_FORMAT
    name = create_unicode_buffer(256)
    length = DWORD(len(name))
    if windll.kernel32.GetComputerNameExW(physical_dns_fully_qualified, name, byref(length)):
        return name.value
    return ""


def _normalize_hostname(name):
    return name.lower().removesuffix(".")


@lru_cache(maxsize=1)
def _machine_hostnames():
    return frozenset(_normalize_hostname(name) for name in (socket.gethostname(), _system_fqdn()) if name)


def tool_allowed(tool, request=None):
    if is_team():
        from app.core import team, team_tools
        if request is None:
            return False
        user = team.request_user(request)
        tool_id = tool.get("id")
        with job_db() as connection:
            connection.execute("BEGIN")
            return tool_id in team_tools.available_tools(connection, user["id"], {tool_id})
    if not is_open_lan():
        return True
    allowed = _listed_values("ORANGE_LAN_TOOLS")
    if "ORANGE_LAN_TOOLS" in os.environ:
        return tool.get("id") in allowed
    return tool.get("provider", "comfyui") == "comfyui"


def enhancement_allowed():
    return not is_open_lan() or os.environ.get("ORANGE_LAN_PROMPT_ENHANCEMENT") == "1"


def _address(host):
    try:
        return ip_address(host)
    except ValueError:
        return None


def _lan_address(address):
    return address is not None and (address.is_loopback or any(address in network for network in _LAN_NETWORKS))


def _lan_host_allowed(host):
    normalized = _normalize_hostname(host)
    if normalized == "localhost" or _lan_address(_address(normalized)):
        return True
    aliases = {_normalize_hostname(value) for value in _listed_values("ORANGE_LAN_HOSTS")}
    return normalized in aliases or normalized in _machine_hostnames()


def allows_direct_lan_http(request):
    # Forwarded clients lack the original socket port in Uvicorn.
    client = request.client
    return bool(request.url.scheme == "http" and lan_http_requested() and client and client.port
                and _lan_address(_address(client.host)))


def is_host_connection(request):
    client = request.client
    peer = _address(client.host) if client else None
    if peer is None or not client.port:
        return False
    if peer.is_loopback:
        return True

    # A direct connection to the host's LAN address uses that same address at both ends.
    # Uvicorn supplies the accepted socket address and uses port zero for forwarded clients.
    server = request.scope.get("server")
    return bool(server and peer == _address(server[0]))


def request_access_error(request):
    peer = _address(request.client.host) if request.client else None
    host = (request.url.hostname or "").lower()
    mode = access_mode()
    if mode == "team":
        origin = os.environ.get("ORANGE_TEAM_ORIGIN", "").strip().rstrip("/")
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        local = peer and peer.is_loopback and (host == "localhost" or (_address(host) and _address(host).is_loopback))
        secure_origin = origin.startswith("https://") and origin == same_origin
        if not local and not secure_origin and not (allows_direct_lan_http(request) and _lan_host_allowed(host)):
            return 403, "Use Team Orange's HTTPS address or enable LAN HTTP on the Orange host."
    elif mode == "open-lan":
        if not _lan_address(peer):
            return 403, "Open LAN access is available on private networks."
        if not _lan_host_allowed(host):
            return 403, "This hostname is not configured for Open LAN access. Set ORANGE_LAN_HOSTS for custom aliases."
        admin_request = request.url.path == "/admin" or request.url.path.startswith("/api/admin/")
        if admin_request and request.url.scheme != "https" and not is_host_connection(request) and not allows_direct_lan_http(request):
            return 403, "Open Admin on the Orange host, use HTTPS, or enable LAN HTTP on the host."
    else:
        if peer is not None and not peer.is_loopback:
            return 403, "This Orange installation is accessible from the host machine."
        if request.headers.get("sec-fetch-site") or request.headers.get("origin"):
            address = _address(host)
            if host != "localhost" and (address is None or not address.is_loopback):
                return 403, "Open Orange using its local address."

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        same_origin = f"{request.url.scheme}://{request.url.netloc}"
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site == "cross-site" or (mode == "team" and fetch_site == "same-site") or (origin and origin != same_origin):
            return 403, "Open Orange directly before sending this request."
    return None


def guest_token(request):
    token = request.cookies.get(GUEST_COOKIE, "") if request else ""
    return token if _GUEST_TOKEN.fullmatch(token) else None


def start_guest_session(request):
    return guest_token(request) or secrets.token_urlsafe(32)


def set_guest_cookie(response, request, token):
    response.set_cookie(
        GUEST_COOKIE, token, max_age=30 * 24 * 3600, httponly=True,
        samesite="lax", secure=request.url.scheme == "https",
    )


def submitting_guest(request):
    if not is_open_lan():
        return None
    token = getattr(request.state, "guest_token", None) or guest_token(request)
    if not token:
        raise HTTPException(403, "Open Generate to start a guest session.")
    return token


def _gallery_signature(value):
    admin_key = str(load_config().get("adminKey", ""))
    return hmac.new(_GALLERY_KEY, f"{admin_key}:{value}".encode(), hashlib.sha256).hexdigest()


def grant_gallery_access(response: Response, request: Request):
    value = f"{int(time.time()) + GALLERY_MAX_AGE}.{secrets.token_urlsafe(16)}"
    response.set_cookie(
        GALLERY_COOKIE, f"{value}.{_gallery_signature(value)}", max_age=GALLERY_MAX_AGE,
        path="/api", httponly=True, samesite="strict", secure=request.url.scheme == "https",
    )


def _has_gallery_access(request):
    if request is None:
        return False
    if request.url.scheme != "https" and not is_host_connection(request) and not allows_direct_lan_http(request):
        return False
    expires, nonce, signature = (request.cookies.get(GALLERY_COOKIE, "").split(".") + [""] * 3)[:3]
    return bool(
        re.fullmatch(r"[0-9]{1,12}", expires)
        and re.fullmatch(r"[a-f0-9]{64}", signature)
        and int(expires) > time.time()
        and hmac.compare_digest(signature, _gallery_signature(f"{expires}.{nonce}"))
    )


@contextmanager
def job_db():
    with closing(sqlite3.connect(JOB_ACCESS_PATH, timeout=5.0)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection


def init_job_access():
    JOB_ACCESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with job_db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS generation_access (
            id TEXT PRIMARY KEY, guest_digest TEXT NOT NULL, tool_id TEXT NOT NULL,
            provider TEXT NOT NULL, prompt_id TEXT, backend_url TEXT, client_id TEXT
        )""")
        existing = {row["name"] for row in connection.execute("PRAGMA table_info(generation_access)")}
        for name, definition in (
            ("owner_id", "TEXT"), ("created", "INTEGER"), ("output_type", "TEXT"), ("status", "TEXT"),
        ):
            if name not in existing:
                connection.execute(f"ALTER TABLE generation_access ADD COLUMN {name} {definition}")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_generation_owner ON generation_access(owner_id, created)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_generation_prompt ON generation_access(prompt_id)")


def reserve_generation(job_id, token, tool_id, provider, *, client_id=None):
    digest = hashlib.sha256(token.encode()).hexdigest()
    with job_db() as connection:
        connection.execute(
            "INSERT INTO generation_access (id, guest_digest, tool_id, provider, client_id) VALUES (?, ?, ?, ?, ?)",
            (job_id, digest, tool_id, provider, client_id),
        )


def insert_owned_generation(connection, job_id, user_id, tool_id, provider, output_type, *, client_id=None):
    connection.execute("""INSERT INTO generation_access
        (id, guest_digest, owner_id, tool_id, provider, output_type, client_id, created, status)
        VALUES (?, '', ?, ?, ?, ?, ?, ?, 'queued')""",
        (job_id, user_id, tool_id, provider, output_type, client_id, int(time.time())),
    )


def attach_comfy_generation(job_id, prompt_id, backend_url):
    with job_db() as connection:
        changed = connection.execute(
            "UPDATE generation_access SET prompt_id = ?, backend_url = ? WHERE id = ? AND prompt_id IS NULL",
            (prompt_id, backend_url, job_id),
        )
        if changed.rowcount != 1:
            raise RuntimeError("Orange could not record the submitted generation.")


def fail_unconfirmed_generation(job_id, status):
    with job_db() as connection:
        connection.execute("UPDATE generation_access SET status=? WHERE id=? AND prompt_id IS NULL", (status, job_id))


def update_owned_comfy_status(prompt_id, backend_url, status):
    if not is_team():
        return
    with job_db() as connection:
        connection.execute("""UPDATE generation_access SET status=?
            WHERE prompt_id=? AND backend_url=? AND owner_id IS NOT NULL
            AND (status IN ('queued', 'running', 'monitor_timeout') OR ? = 'completed')""",
            (status, prompt_id, backend_url, status),
        )


def authorize_generation(request, job_id, *, gallery=False):
    if is_team():
        user = getattr(request.state, "team_user", None) if request else None
        if user:
            with job_db() as connection:
                row = connection.execute("SELECT * FROM generation_access WHERE id=? AND owner_id=?", (job_id, user["id"])).fetchone()
            if row is not None and (row["provider"] != "comfyui" or row["prompt_id"]):
                return row
        raise HTTPException(404, "Generation was not found.")
    if not is_open_lan():
        return None
    token = guest_token(request)
    if token:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with job_db() as connection:
            row = connection.execute(
                "SELECT * FROM generation_access WHERE id = ? AND guest_digest = ?", (job_id, digest),
            ).fetchone()
        if row is not None and (row["provider"] != "comfyui" or row["prompt_id"]):
            return row
    if gallery and _has_gallery_access(request):
        return None
    raise HTTPException(404, "Generation was not found.")
