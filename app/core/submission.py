from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass
class SubmissionFailure(Exception):
    public_message: str
    technical_message: str
    status_code: int = 503
    retryable: bool = False
    mark_backend_failed: bool = False

    def __str__(self) -> str:
        return self.technical_message or self.public_message


def _response_detail(response: httpx.Response, limit: int = 4000) -> str:
    try:
        text = response.text
    except Exception:
        text = ""
    clean = " ".join(str(text or "").split())
    return clean[:limit]


async def upload_image_bytes(
    client: httpx.AsyncClient,
    target_url: str,
    filename: str,
    image_bytes: bytes,
    content_type: str,
) -> str:
    files = {"image": (filename, image_bytes, content_type)}
    try:
        response = await client.post(f"{target_url.rstrip('/')}/upload/image", files=files, timeout=30.0)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
        # Uploading an image is idempotent for Orange's purposes; retrying on a
        # different backend cannot accidentally duplicate a generation.
        raise SubmissionFailure(
            public_message="A generation backend became unavailable while preparing the request.",
            technical_message=f"Image upload transport failure: {type(exc).__name__}: {exc}",
            status_code=503,
            retryable=True,
            mark_backend_failed=True,
        )

    if 400 <= response.status_code < 500:
        detail = _response_detail(response)
        raise SubmissionFailure(
            public_message="A required image could not be accepted by the generation backend.",
            technical_message=f"Image upload rejected with HTTP {response.status_code}: {detail}",
            status_code=422,
            retryable=False,
            mark_backend_failed=False,
        )
    if response.status_code >= 500:
        detail = _response_detail(response)
        raise SubmissionFailure(
            public_message="A generation backend failed while preparing the request.",
            technical_message=f"Image upload failed with HTTP {response.status_code}: {detail}",
            status_code=503,
            retryable=True,
            mark_backend_failed=True,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise SubmissionFailure(
            public_message="A generation backend returned an invalid upload response.",
            technical_message=f"Image upload returned invalid JSON: {exc}",
            status_code=502,
            retryable=True,
            mark_backend_failed=True,
        )
    uploaded_name = payload.get("name") if isinstance(payload, dict) else None
    if not uploaded_name:
        raise SubmissionFailure(
            public_message="A generation backend returned an invalid upload response.",
            technical_message="Image upload response did not contain a filename.",
            status_code=502,
            retryable=True,
            mark_backend_failed=True,
        )
    return str(uploaded_name)


async def submit_prompt(
    client: httpx.AsyncClient,
    target_url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    url = f"{target_url.rstrip('/')}/prompt"
    try:
        response = await client.post(url, json=payload, timeout=30.0)
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        # These failures happen before Orange has a usable connection to ComfyUI,
        # so moving to another backend is safe.
        raise SubmissionFailure(
            public_message="A generation backend could not be reached.",
            technical_message=f"Prompt connect failure: {type(exc).__name__}: {exc}",
            status_code=503,
            retryable=True,
            mark_backend_failed=True,
        )
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as exc:
        # Once a request may have reached ComfyUI, automatically submitting it to
        # another backend risks creating a duplicate generation. Fail closed.
        raise SubmissionFailure(
            public_message="The backend connection was lost while submitting the generation. It may still have started; check the admin dashboard before trying again.",
            technical_message=f"Ambiguous prompt submission failure: {type(exc).__name__}: {exc}",
            status_code=502,
            retryable=False,
            mark_backend_failed=True,
        )

    if 400 <= response.status_code < 500:
        detail = _response_detail(response)
        # ComfyUI returned an explicit rejection, so this prompt was not queued.
        # The rejection may be backend-specific (for example a model/LoRA/CLIP
        # value missing on this machine), so trying another backend is safe and is
        # exactly what Orange's failover layer is for. Do not mark the whole server
        # unhealthy: /queue and unrelated workflows may still work perfectly.
        raise SubmissionFailure(
            public_message="The workflow was rejected by this generation backend.",
            technical_message=f"ComfyUI rejected /prompt with HTTP {response.status_code}: {detail}",
            status_code=422,
            retryable=True,
            mark_backend_failed=False,
        )
    if response.status_code >= 500:
        detail = _response_detail(response)
        raise SubmissionFailure(
            public_message="A generation backend failed while accepting the request.",
            technical_message=f"ComfyUI /prompt failed with HTTP {response.status_code}: {detail}",
            status_code=503,
            retryable=True,
            mark_backend_failed=True,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise SubmissionFailure(
            public_message="The backend returned an invalid response while starting the generation. It may still have started; check the admin dashboard before trying again.",
            technical_message=f"Prompt response was not valid JSON: {exc}",
            status_code=502,
            retryable=False,
            mark_backend_failed=True,
        )

    if not isinstance(data, dict) or not data.get("prompt_id"):
        raise SubmissionFailure(
            public_message="The backend did not confirm the generation ID. It may still have started; check the admin dashboard before trying again.",
            technical_message=f"Prompt response did not contain prompt_id: {data!r}"[:4000],
            status_code=502,
            retryable=False,
            mark_backend_failed=True,
        )
    return data
