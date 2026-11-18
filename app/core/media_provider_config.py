"""Provider settings contain no secrets; credentials use Orange's native vault."""
import hashlib
import json
import os
from pathlib import Path
import threading
from datetime import datetime, timezone
from dataclasses import asdict

from app.core.config import PROJECT_ROOT
from app.core.huggingface import _credential_store, CREDENTIAL_STORAGE_ERROR
from app.core.media_providers import MODELS, model_for, provider_models

SETTINGS_PATH = Path(PROJECT_ROOT) / "workflows" / ".runtime" / "api-providers.json"
_LOCK = threading.RLock()
ENV_KEYS = {"openai": ("ORANGE_OPENAI_API_KEY", "OPENAI_API_KEY"), "google": ("ORANGE_GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")}
ENV_KEYS["anthropic"] = ("ORANGE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
ENV_KEYS["openrouter"] = ("ORANGE_OPENROUTER_API_KEY", "OPENROUTER_API_KEY")
ENV_KEYS["venice"] = ("ORANGE_VENICE_API_KEY", "VENICE_API_KEY")
ENV_KEYS["xai"] = ("ORANGE_XAI_API_KEY", "XAI_API_KEY")
ENV_KEYS["runway"] = ("ORANGE_RUNWAY_API_KEY", "RUNWAYML_API_SECRET", "RUNWAY_API_KEY")
ENV_KEYS["fal"] = ("ORANGE_FAL_API_KEY", "FAL_KEY", "FAL_API_KEY")


def _vault(provider, method, *args):
    if provider not in ENV_KEYS:
        raise ValueError("Unknown credential provider.")
    identity = hashlib.sha256(str(SETTINGS_PATH.resolve()).encode()).hexdigest()
    try:
        return getattr(_credential_store(), method)(f"Orange.Media.{identity}", provider, *args)
    except Exception:
        raise OSError(CREDENTIAL_STORAGE_ERROR) from None


def credential(provider):
    for name in ENV_KEYS[provider]:
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return _vault(provider, "get_password") or ""


def settings():
    with _LOCK:
        try:
            value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError
            return value
        except FileNotFoundError:
            return {}


def enabled(provider, model):
    config = settings().get(provider, {})
    model_for(provider, model)
    return config.get("enabled", False)


def ready(provider, model):
    try:
        return bool(enabled(provider, model) and credential(provider))
    except (OSError, ValueError):
        return False


def public_settings():
    result = []
    config = settings()
    for provider in [*MODELS, *(name for name in ENV_KEYS if name not in MODELS)]:
        models = provider_models(provider)
        item = config.get(provider, {})
        environment = any(os.environ.get(name, "").strip() for name in ENV_KEYS[provider])
        try:
            configured = bool(credential(provider))
            storage_error = None
        except OSError:
            configured, storage_error = False, CREDENTIAL_STORAGE_ERROR
        result.append({"id": provider, "enabled": item.get("enabled", False), "models": item.get("discoveredModels", []),
                       "discoveredAt": item.get("discoveredAt"),
                       "configured": configured,
                       "supportsMedia": provider in MODELS,
                       "source": "environment" if environment else "saved" if configured else "none",
                       "storageError": storage_error,
                       "catalog": [{"id": m.id, "name": m.name, "output": m.output, "ratios": m.ratios,
                                    "resolutions": m.resolutions, "durations": m.durations, "references": m.references, "requiresImage": m.requires_image,
                                    "sourceAspect": m.source_aspect, "referenceAspect": m.reference_aspect, "promptLimit": m.prompt_limit} for m in models]})
    return result


def save_provider(provider, payload):
    if provider not in ENV_KEYS or not isinstance(payload, dict):
        raise ValueError("Unknown API provider.")
    if set(payload) - {"enabled", "models", "apiKey", "clearCredential"}:
        raise ValueError("Unsupported provider settings.")
    if type(payload.get("enabled")) is not bool or not isinstance(payload.get("models", []), list):
        raise ValueError("Choose whether to enable this provider.")
    if type(payload.get("clearCredential", False)) is not bool:
        raise ValueError("Credential removal must be true or false.")
    for model in payload.get("models", []):
        model_for(provider, model)
    key = payload.get("apiKey", "")
    if not isinstance(key, str) or len(key) > 1000 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError("Enter a valid API credential without whitespace.")
    with _LOCK:
        config = settings()
        item = config.get(provider, {})
        credential_changed = bool(payload.get("clearCredential"))
        if payload.get("clearCredential"):
            if _vault(provider, "get_password") is not None:
                _vault(provider, "delete_password")
        elif key:
            credential_changed = _vault(provider, "get_password") != key
            _vault(provider, "set_password", key)
        item = {**item, "enabled": payload["enabled"]}
        item.pop("rates", None)
        item.pop("scrubMetadata", None)
        item.pop("models", None)  # Legacy manual model enablement is no longer needed.
        if credential_changed:
            item.pop("discoveredModels", None)
            item.pop("discoveredAt", None)
        config[provider] = item
        _write_settings(config)


def _write_settings(config):
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(temporary, SETTINGS_PATH)


def save_discovery(provider, model_ids, key, definitions=None):
    """Save only compatible model IDs; never persist arbitrary catalog content."""
    with _LOCK:
        if credential(provider) != key:
            raise ValueError("The credential changed. Test the connection again.")
        catalog = definitions if definitions is not None else provider_models(provider)
        supported = {model.id for model in catalog}
        available = sorted({value for value in model_ids if isinstance(value, str) and value in supported})
        config = settings()
        item = config.setdefault(provider, {})
        if definitions is not None:
            previous = {m.id: asdict(m) for m in provider_models(provider)}
            previous.update({m.id: asdict(m) for m in definitions})
            item["modelDefinitions"] = list(previous.values())
        item.update(discoveredModels=available, discoveredAt=datetime.now(timezone.utc).isoformat())
        _write_settings(config)
        return available
