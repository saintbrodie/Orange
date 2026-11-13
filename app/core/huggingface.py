"""Server-only Hugging Face credentials and authenticated model downloads."""
import hashlib
import os
from pathlib import Path
import re
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from app.core.config import PROJECT_ROOT

TOKEN_PATH = Path(PROJECT_ROOT) / "runtime" / "secrets" / "huggingface-token"
TOKEN_PATTERN = re.compile(r"hf_[A-Za-z0-9_]{5,500}")
_STORE_LOCK = threading.RLock()
_SERVICE = "Orange.HuggingFace"
CREDENTIAL_STORAGE_ERROR = (
    "Orange could not access the operating system credential store. "
    "Install Orange's dependencies and unlock your Windows credential store, "
    "macOS Keychain, or Linux Secret Service, or configure HF_TOKEN on the server."
)


def _credential_store():
    # Instantiate only native backends. Never accept configured/plugin backends,
    # including keyrings.alt's plaintext files or the silent null backend.
    try:
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring
            backend = WinVaultKeyring()
            backend.persist = "local machine"
        elif sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
            backend = Keyring()
        elif sys.platform.startswith("linux"):
            from keyring.backends.SecretService import Keyring
            backend = Keyring()
        else:
            raise OSError(CREDENTIAL_STORAGE_ERROR)
        if backend.priority <= 0:
            raise OSError(CREDENTIAL_STORAGE_ERROR)
        return backend
    except Exception:
        raise OSError(CREDENTIAL_STORAGE_ERROR) from None


def _account():
    # Isolate separate Orange installations under the same operating system user.
    identity = os.path.normcase(str(TOKEN_PATH.resolve()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _store_call(backend, method, *args):
    try:
        return getattr(backend, method)(f"{_SERVICE}.{_account()}", "token", *args)
    except Exception:
        # Backend exceptions may contain credentials; never propagate them.
        raise OSError(CREDENTIAL_STORAGE_ERROR) from None


def _write_verified(backend, value):
    _store_call(backend, "set_password", value)
    if _store_call(backend, "get_password") != value:
        raise OSError(CREDENTIAL_STORAGE_ERROR)


def _saved_token():
    with _STORE_LOCK:
        backend = _credential_store()
        saved = _store_call(backend, "get_password")
        try:
            legacy = TOKEN_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return saved or ""
        except (OSError, UnicodeError):
            raise OSError("Could not migrate the old Hugging Face token file.") from None
        if not saved and legacy:
            if not TOKEN_PATTERN.fullmatch(legacy):
                raise OSError("The old Hugging Face token file is invalid. Save a new token or remove it.")
            _write_verified(backend, legacy)
            saved = legacy
        # Delete plaintext only after native storage has confirmed the write.
        # An existing native credential always takes precedence over a stale file.
        TOKEN_PATH.unlink(missing_ok=True)
        return saved or ""


def get_token():
    return os.environ.get("HF_TOKEN", "").strip() or _saved_token()


def token_status():
    environment = bool(os.environ.get("HF_TOKEN", "").strip())
    saved = bool(_saved_token())
    return {"configured": environment or saved, "saved": saved,
            "source": "environment" if environment else "saved" if saved else "none"}


def save_token(value):
    if not isinstance(value, str) or not TOKEN_PATTERN.fullmatch(value.strip()):
        raise ValueError("Enter a Hugging Face access token beginning with hf_.")
    with _STORE_LOCK:
        _write_verified(_credential_store(), value.strip())
        TOKEN_PATH.unlink(missing_ok=True)


def clear_token():
    with _STORE_LOCK:
        backend = _credential_store()
        # Remove the legacy copy first so a failed delete cannot resurrect it.
        TOKEN_PATH.unlink(missing_ok=True)
        if _store_call(backend, "get_password") is not None:
            _store_call(backend, "delete_password")


def _is_hub_url(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "huggingface.co"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def auth_headers(url):
    if not _is_hub_url(url):
        return {}
    token = get_token()
    if token and not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("The Hugging Face token format is invalid. Check HF_TOKEN or the saved token.")
    return {"Authorization": f"Bearer {token}"} if token else {}


class _HubRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Authorization lives in unredirected_hdrs, so urllib never copies it
        # to signed storage/CDN URLs. Retain it only within the HTTPS Hub origin.
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        authorization = request.get_header("Authorization")
        if redirected is not None:
            redirected.remove_header("Authorization")
            if authorization and _is_hub_url(new_url):
                redirected.add_unredirected_header("Authorization", authorization)
        return redirected


def open_model_download(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": "Orange/1.0"})
    for key, value in auth_headers(url).items():
        request.add_unredirected_header(key, value)
    try:
        if request.has_header("Authorization"):
            opener = urllib.request.build_opener(_HubRedirectHandler())
            return opener.open(request, timeout=timeout)
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if _is_hub_url(url) and exc.code in (401, 403):
            raise ValueError(
                "Hugging Face denied model access. Add or check your read token in "
                "General Settings, and accept the model's terms on Hugging Face before retrying."
            ) from None
        raise ValueError(f"Model download failed (HTTP {exc.code}).") from None
