"""Server-only Civitai download credentials; never attach them to storage URLs."""
import hashlib
import os
from urllib.parse import urlsplit

from app.core.config import PROJECT_ROOT
from app.core.huggingface import _credential_store, CREDENTIAL_STORAGE_ERROR


def _vault(method, *args):
    identity = hashlib.sha256(os.path.normcase(PROJECT_ROOT).encode()).hexdigest()
    try:
        return getattr(_credential_store(), method)(f"Orange.Civitai.{identity}", "token", *args)
    except Exception:
        raise OSError(CREDENTIAL_STORAGE_ERROR) from None


def get_token():
    return os.environ.get("CIVITAI_API_KEY", "").strip() or os.environ.get("CIVITAI_TOKEN", "").strip() or _vault("get_password") or ""


def token_status():
    environment = bool(os.environ.get("CIVITAI_API_KEY", "").strip() or os.environ.get("CIVITAI_TOKEN", "").strip())
    try:
        saved = bool(_vault("get_password"))
    except OSError:
        if not environment:
            raise
        saved = False
    return {"configured": environment or saved, "saved": saved, "source": "environment" if environment else "saved" if saved else "none"}


def save_token(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 1000 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("Enter a valid Civitai API key without whitespace.")
    _vault("set_password", value)


def clear_token():
    if _vault("get_password") is not None:
        _vault("delete_password")


def is_civitai_url(url):
    try:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname == "civitai.com" and parsed.port in (None, 443) and not parsed.username and not parsed.password
    except ValueError:
        return False


def auth_headers(url):
    if not is_civitai_url(url):
        return {}
    token = get_token()
    if token and any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Civitai credential is invalid. Check API Keys.")
    return {"Authorization": f"Bearer {token}"} if token else {}
