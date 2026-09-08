import ipaddress
import os
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx


SUPPORTED_PROVIDERS = {"openai", "ollama", "gemini", "anthropic"}
ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class LLMError(Exception):
    def __init__(self, public_message: str, technical_message: str, status_code: int = 502):
        super().__init__(technical_message)
        self.public_message = public_message
        self.technical_message = technical_message
        self.status_code = status_code


class LLMConfigError(LLMError):
    def __init__(self, public_message: str, technical_message: Optional[str] = None):
        super().__init__(public_message, technical_message or public_message, status_code=400)


def normalize_provider(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if value not in SUPPORTED_PROVIDERS:
        raise LLMConfigError("Prompt enhancement provider is not supported.", f"Unsupported LLM provider: {value!r}")
    return value


def validate_model(model: str) -> str:
    value = str(model or "").strip()
    if not value:
        raise LLMConfigError("Prompt enhancement model is not configured.")
    if len(value) > 256 or any(ord(char) < 32 for char in value):
        raise LLMConfigError("Prompt enhancement model name is invalid.")
    return value


def validate_base_url(base_url: Optional[str]) -> Optional[str]:
    value = str(base_url or "").strip()
    if not value:
        return None
    if len(value) > 2048:
        raise LLMConfigError("Prompt enhancement base URL is invalid.")

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LLMConfigError("Prompt enhancement base URL must be an HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise LLMConfigError("Prompt enhancement base URL must not contain credentials.")
    if parsed.query or parsed.fragment:
        raise LLMConfigError("Prompt enhancement base URL must not contain a query string or fragment.")

    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def resolve_api_key(provider: str, api_key: Optional[str]) -> Optional[str]:
    provider = normalize_provider(provider)
    env_name = ENV_KEYS.get(provider)
    env_value = os.environ.get(env_name) if env_name else None
    value = env_value or str(api_key or "").strip()
    return value or None


def _is_local_url(base_url: Optional[str]) -> bool:
    if not base_url:
        return False
    hostname = (urlsplit(base_url).hostname or "").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return False


def _timeout_seconds() -> float:
    try:
        value = float(os.environ.get("ORANGE_LLM_TIMEOUT_SECONDS", "30"))
    except (TypeError, ValueError):
        value = 30.0
    return min(120.0, max(3.0, value))


def _max_tokens() -> int:
    try:
        value = int(os.environ.get("ORANGE_LLM_MAX_TOKENS", "512"))
    except (TypeError, ValueError):
        value = 512
    return min(4096, max(64, value))


def _redact(value: Any, resolved_key: Optional[str] = None, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    if resolved_key:
        text = text.replace(resolved_key, "[REDACTED]")
    return text[:limit]


def _endpoint(base_url: Optional[str], default_base: str, suffix: str) -> str:
    base = (base_url or default_base).rstrip("/")
    return f"{base}/{suffix.lstrip('/')}"


def _anthropic_endpoint(base_url: Optional[str], endpoint: str) -> str:
    base = (base_url or "https://api.anthropic.com").rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/{endpoint.lstrip('/')}"
    return f"{base}/v1/{endpoint.lstrip('/')}"


def _gemini_endpoint(base_url: Optional[str], suffix: str) -> str:
    base = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
    if base.endswith("/v1beta"):
        return f"{base}/{suffix.lstrip('/')}"
    return f"{base}/v1beta/{suffix.lstrip('/')}"


def _require_cloud_key(provider: str, base_url: Optional[str], resolved_key: Optional[str]) -> None:
    if resolved_key:
        return
    if provider == "ollama":
        return
    if base_url and _is_local_url(base_url):
        return
    if provider in {"openai", "gemini", "anthropic"} and not base_url:
        raise LLMConfigError(f"API key is missing for {provider.capitalize()} prompt enhancement.")
    if provider == "openai" and base_url and "api.openai.com" in (urlsplit(base_url).hostname or ""):
        raise LLMConfigError("OpenAI API key is missing for prompt enhancement.")
    if provider == "gemini" and base_url and "googleapis.com" in (urlsplit(base_url).hostname or ""):
        raise LLMConfigError("Gemini API key is missing for prompt enhancement.")
    if provider == "anthropic" and base_url and "anthropic.com" in (urlsplit(base_url).hostname or ""):
        raise LLMConfigError("Anthropic API key is missing for prompt enhancement.")


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: dict,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    resolved_key: Optional[str] = None,
) -> dict:
    try:
        response = await client.post(url, json=payload, headers=headers or {}, params=params or {})
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = _redact(exc.response.text, resolved_key)
        raise LLMError(
            "Prompt enhancement service returned an error.",
            f"Provider HTTP {exc.response.status_code}: {body}",
            status_code=502,
        )
    except httpx.TimeoutException as exc:
        raise LLMError(
            "Prompt enhancement service timed out.",
            f"LLM request timeout: {type(exc).__name__}: {_redact(exc, resolved_key)}",
            status_code=504,
        )
    except httpx.HTTPError as exc:
        raise LLMError(
            "Prompt enhancement service is unavailable.",
            f"LLM transport failure: {type(exc).__name__}: {_redact(exc, resolved_key)}",
            status_code=502,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise LLMError(
            "Prompt enhancement service returned an invalid response.",
            f"Provider returned invalid JSON: {_redact(exc, resolved_key)}",
        )
    if not isinstance(data, dict):
        raise LLMError(
            "Prompt enhancement service returned an invalid response.",
            f"Provider JSON was {type(data).__name__}, expected object",
        )
    return data


def _clean_output(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise LLMError(
            "Prompt enhancement service returned an empty response.",
            "Provider response contained no usable text.",
        )
    return text


async def call_llm(
    provider: str,
    base_url: Optional[str],
    api_key: Optional[str],
    model: str,
    system_prompt: str,
    prompt: str,
) -> str:
    """Call a configured prompt-enhancement provider without exposing provider internals."""
    provider = normalize_provider(provider)
    base_url = validate_base_url(base_url)
    model = validate_model(model)
    system_prompt = str(system_prompt or "").strip()
    prompt = str(prompt or "").strip()
    if not system_prompt:
        raise LLMConfigError("Prompt enhancement instructions are not configured.")
    if not prompt:
        raise LLMConfigError("Prompt enhancement requires a prompt.")

    resolved_key = resolve_api_key(provider, api_key)
    _require_cloud_key(provider, base_url, resolved_key)

    timeout = httpx.Timeout(_timeout_seconds())
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        if provider == "openai":
            url = _endpoint(base_url, "https://api.openai.com/v1", "chat/completions")
            headers = {"Authorization": f"Bearer {resolved_key}"} if resolved_key else {}
            data = await _post_json(
                client,
                url,
                payload={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                },
                headers=headers,
                resolved_key=resolved_key,
            )
            try:
                return _clean_output(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError):
                raise LLMError(
                    "Prompt enhancement service returned an invalid response.",
                    "OpenAI-compatible response was missing choices[0].message.content.",
                )

        if provider == "ollama":
            url = _endpoint(base_url, "http://127.0.0.1:11434", "api/chat")
            data = await _post_json(
                client,
                url,
                payload={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                },
            )
            try:
                return _clean_output(data["message"]["content"])
            except (KeyError, TypeError):
                raise LLMError(
                    "Prompt enhancement service returned an invalid response.",
                    "Ollama response was missing message.content.",
                )

        if provider == "gemini":
            url = _gemini_endpoint(base_url, f"models/{model}:generateContent")
            data = await _post_json(
                client,
                url,
                payload={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                },
                params={"key": resolved_key} if resolved_key else {},
                resolved_key=resolved_key,
            )
            try:
                return _clean_output(data["candidates"][0]["content"]["parts"][0]["text"])
            except (KeyError, IndexError, TypeError):
                raise LLMError(
                    "Prompt enhancement service returned an invalid response.",
                    "Gemini response was missing candidates[0].content.parts[0].text.",
                )

        url = _anthropic_endpoint(base_url, "messages")
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if resolved_key:
            headers["x-api-key"] = resolved_key
        data = await _post_json(
            client,
            url,
            payload={
                "model": model,
                "max_tokens": _max_tokens(),
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
            },
            headers=headers,
            resolved_key=resolved_key,
        )
        try:
            return _clean_output(data["content"][0]["text"])
        except (KeyError, IndexError, TypeError):
            raise LLMError(
                "Prompt enhancement service returned an invalid response.",
                "Anthropic response was missing content[0].text.",
            )


async def list_llm_models(
    provider: str,
    base_url: Optional[str],
    api_key: Optional[str],
) -> list[str]:
    provider = normalize_provider(provider)
    base_url = validate_base_url(base_url)
    resolved_key = resolve_api_key(provider, api_key)
    _require_cloud_key(provider, base_url, resolved_key)

    timeout = httpx.Timeout(min(_timeout_seconds(), 20.0))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            if provider == "ollama":
                url = _endpoint(base_url, "http://127.0.0.1:11434", "api/tags")
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                models = [item.get("name") for item in data.get("models", []) if isinstance(item, dict)]
            elif provider == "openai":
                url = _endpoint(base_url, "https://api.openai.com/v1", "models")
                headers = {"Authorization": f"Bearer {resolved_key}"} if resolved_key else {}
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                models = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
            elif provider == "gemini":
                url = _gemini_endpoint(base_url, "models")
                response = await client.get(url, params={"key": resolved_key} if resolved_key else {})
                response.raise_for_status()
                data = response.json()
                models = [
                    str(item.get("name", "")).removeprefix("models/")
                    for item in data.get("models", [])
                    if isinstance(item, dict)
                ]
            else:
                url = _anthropic_endpoint(base_url, "models")
                headers = {"anthropic-version": "2023-06-01"}
                if resolved_key:
                    headers["x-api-key"] = resolved_key
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                models = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
        except httpx.HTTPStatusError as exc:
            body = _redact(exc.response.text, resolved_key)
            raise LLMError(
                "Could not fetch models from the prompt enhancement service.",
                f"Model list HTTP {exc.response.status_code}: {body}",
            )
        except httpx.TimeoutException as exc:
            raise LLMError(
                "Prompt enhancement service timed out while listing models.",
                f"Model list timeout: {type(exc).__name__}: {_redact(exc, resolved_key)}",
                status_code=504,
            )
        except httpx.HTTPError as exc:
            raise LLMError(
                "Prompt enhancement service is unavailable.",
                f"Model list transport failure: {type(exc).__name__}: {_redact(exc, resolved_key)}",
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise LLMError(
                "Prompt enhancement service returned an invalid model list.",
                f"Model list parse failure: {type(exc).__name__}: {_redact(exc, resolved_key)}",
            )

    return sorted({str(model).strip() for model in models if str(model or "").strip()}, key=str.lower)
