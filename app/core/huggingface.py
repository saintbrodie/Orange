"""Server-only Hugging Face credentials and authenticated model downloads."""
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from app.core.config import PROJECT_ROOT

TOKEN_PATH = Path(PROJECT_ROOT) / "runtime" / "secrets" / "huggingface-token"
TOKEN_PATTERN = re.compile(r"hf_[A-Za-z0-9_]{5,500}")


def _saved_token():
    try:
        return TOKEN_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


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
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=TOKEN_PATH.parent, prefix=".hf-token-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value.strip())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, TOKEN_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clear_token():
    TOKEN_PATH.unlink(missing_ok=True)


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
