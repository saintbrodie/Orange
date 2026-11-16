"""Curated media capabilities and transport-independent provider registry.

REST contracts verified 2026-11-16; see docs/API_PROVIDERS.md. No provider SDK
is required: Orange already owns an asynchronous httpx transport.
"""
import base64
import binascii
import re
from urllib.parse import urljoin, urlsplit
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    output: str = "image"
    ratios: tuple = ("1:1", "3:2", "2:3")
    resolutions: tuple = ("standard",)
    durations: tuple = ()
    references: int = 2
    requires_image: bool = False
    send_ratio: bool = True
    pixel_dimensions: bool = False
    prompt_limit: int = 10000
    source_aspect: bool = False
    reference_aspect: bool = False


MODELS = {
    "google": (
        Model("gemini-nano-banana-2.1", "Nano Banana 2.1", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), resolutions=("1K", "2K", "4K")),
        Model("gemini-3.1-flash-image", "Nano Banana 2", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), resolutions=("1K", "2K", "4K")),
        Model("gemini-3-pro-image", "Nano Banana Pro", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), resolutions=("1K", "2K", "4K")),
        Model("gemini-omni-1.2-flash", "Omni 1.2 Flash", "video", ("16:9", "9:16"), ("720p", "1080p"), (5, 10, 15)),
    ),
    "openai": (
        Model("gpt-image-2.6-sunburst", "GPT Image 2.6 Sunburst"),
        Model("gpt-image-2.6-flare", "GPT Image 2.6 Flare"),
        Model("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst"),
        Model("gpt-image-2.5-flare", "GPT Image 2.5 Flare"),
        Model("gpt-image-2", "GPT Image 2"),
        Model("gpt-image-1.5", "GPT Image 1.5"),
        Model("gpt-image-1-mini", "GPT Image 1 Mini"),
    ),
    "openrouter": (),
    "venice": (),
    "xai": (
        Model("grok-imagine-image-2.0", "Grok Imagine Image 2.0", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), resolutions=("1K", "2K"), references=1),
        Model("grok-imagine-video-1.5", "Grok Imagine Video 1.5", "video", ("16:9", "9:16", "1:1"), ("720p", "1080p"), (5, 10, 15), references=1, reference_aspect=True),
        Model("grok-imagine-video-1.5-lite", "Grok Imagine Video 1.5 Lite", "video", ("16:9", "9:16", "1:1"), ("720p", "1080p"), (5, 10, 15), references=1, reference_aspect=True),
    ),
    "runway": (
        Model("gen4_image", "Gen-4 Image", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), prompt_limit=1000),
        Model("gen4_image_turbo", "Gen-4 Image Turbo", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), requires_image=True, prompt_limit=1000),
        Model("gen4.5", "Gen-4.5", "video", ("16:9", "9:16"), ("720p",), (5, 10), references=1, prompt_limit=1000),
        Model("gen4_turbo", "Gen-4 Turbo", "video", ("16:9", "9:16"), ("720p",), (5, 10), references=1, requires_image=True, prompt_limit=1000),
    ),
    "fal": (
        Model("fal-ai/flux-2-pro", "FLUX.2 Pro", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), references=0),
        Model("fal-ai/flux-2-pro/edit", "FLUX.2 Pro Edit", ratios=("1:1", "16:9", "9:16", "4:3", "3:4"), requires_image=True),
        Model("kling/v4/flash/text-to-video", "Kling 4.0 Flash · Text to Video", "video", ("16:9", "9:16", "1:1", "21:9"), ("720p",), (5, 10, 15), references=0),
        Model("kling/v4/flash/image-to-video", "Kling 4.0 Flash · Image to Video", "video", ("source",), ("720p",), (5, 10, 15), references=1, requires_image=True, source_aspect=True),
    ),
}


def provider_models(provider):
    if provider in {"openrouter", "venice"}:
        from app.core.media_provider_config import settings
        models = []
        for item in settings().get(provider, {}).get("modelDefinitions", []):
            try:
                model = Model(**item)
                if valid_model_id(model.id):
                    models.append(model)
            except (TypeError, ValueError):
                continue
        return tuple(models)
    return MODELS.get(provider, ())


def valid_model_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value)) and ".." not in value


@dataclass
class ModelDiscovery:
    models: list


def model_for(provider, model_id):
    if not isinstance(provider, str) or not isinstance(model_id, str):
        raise ValueError("Select a supported media model.")
    for model in provider_models(provider):
        if model.id == model_id:
            return model
    raise ValueError("Select a supported media model.")


def validate_api_tool(tool):
    """The same capability checks protect Admin saves and generation requests."""
    model = model_for(tool.get("provider"), tool.get("model"))
    if tool.get("outputType") != model.output:
        raise ValueError("Tool output type must match the selected model.")
    settings = tool.get("api")
    if not isinstance(settings, dict) or set(settings) - {"ratios", "resolutions", "defaultResolution", "references", "requireImage", "durations", "defaultDuration", "systemPrompt"}:
        raise ValueError("API tools need curated input settings.")
    if not isinstance(settings.get("systemPrompt", ""), str) or len(settings.get("systemPrompt", "")) > 10000:
        raise ValueError("System prompt must be text of at most 10000 characters.")
    source_aspect = model.source_aspect or (model.reference_aspect and bool(settings.get('references')))
    for key, allowed in (("ratios", ('source',) if source_aspect else model.ratios), ("resolutions", model.resolutions)):
        choices = settings.get(key)
        if not isinstance(choices, list) or not choices or any(not isinstance(c, str) or c not in allowed for c in choices) or len(choices) != len(set(choices)):
            raise ValueError(f"Choose supported {key} for this model.")
    if settings.get("defaultResolution") not in settings["resolutions"]:
        raise ValueError("Default resolution must be an available choice.")
    count = settings.get("references", 0)
    if type(count) is not int or not 0 <= count <= model.references:
        raise ValueError("Choose zero, one, or two reference images.")
    if type(settings.get("requireImage", False)) is not bool or (settings.get("requireImage") and not count):
        raise ValueError("An editing tool needs at least one reference image.")
    if model.requires_image and (not settings.get("requireImage") or not count):
        raise ValueError("This model requires an input image for editing.")
    if model.reference_aspect and count and not settings.get('requireImage'):
        raise ValueError('This video tool needs a required starting image, or zero references for text to video.')
    if model.output == "video":
        choices = settings.get("durations")
        if not isinstance(choices, list) or not choices or any(type(c) is not int or c not in model.durations for c in choices) or len(choices) != len(set(choices)):
            raise ValueError("Choose supported video durations.")
        if type(settings.get("defaultDuration")) is not int or settings["defaultDuration"] not in choices:
            raise ValueError("Default duration must be an available choice.")
    elif "durations" in settings or "defaultDuration" in settings:
        raise ValueError("Image tools cannot expose video duration.")
    if any(key in tool for key in ("workflowFile", "imageVariant", "referenceVariant", "duration")):
        raise ValueError("API tools use curated inputs instead of workflow mappings.")
    return model


@dataclass
class MediaRequest:
    model: str
    prompt: str
    aspect_ratio: str
    resolution: str
    duration: int | None = None
    images: list = field(default_factory=list)  # (filename, validated bytes, MIME)


@dataclass
class Media:
    data: bytes
    mime: str


@dataclass
class ProviderResult:
    media: list = field(default_factory=list)
    remote_id: str | None = None  # opaque, server-only file/interaction handle
    usage: dict = field(default_factory=dict)


class ProviderError(Exception):
    """Only constant public messages cross the adapter boundary."""


def _decode(data):
    try:
        if not isinstance(data, str) or len(data) > 360_000_000:
            raise ValueError
        return base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        raise ProviderError("Provider returned invalid media data.") from None


def _usage(payload):
    # Never persist arbitrary response content (which can echo keys or prompts).
    names = {"input_tokens": "input_tokens", "output_tokens": "output_tokens", "total_tokens": "total_tokens",
             "total_input_tokens": "input_tokens", "total_output_tokens": "output_tokens",
             "prompt_tokens": "input_tokens", "completion_tokens": "output_tokens"}
    return {names[k]: v for k, v in payload.items() if k in names and type(v) is int and v >= 0} if isinstance(payload, dict) else {}


async def _request(client, method, url, *, allow_redirect=False, **kwargs):
    """Retry explicit throttling/pre-connect failures; never replay uncertain POSTs."""
    import asyncio
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            raise ProviderError("Could not connect to the media provider.") from None
        except httpx.HTTPError:
            if method == "GET" and attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            raise ProviderError("Provider connection was interrupted. The request may have been accepted; check provider usage before trying again.") from None
        if (response.status_code == 429 or (method == "GET" and response.status_code in {408, 500, 502, 503, 504})) and attempt < 2:
            try:
                delay = min(30, max(1, float(response.headers.get("retry-after", 2 ** attempt))))
            except ValueError:
                delay = 2 ** attempt
            await asyncio.sleep(delay)
            continue
        if response.status_code >= 400:
            message = {
                401: "Provider authentication failed. Check the API credential in Admin.",
                403: "Provider denied access. Check model access and billing in your provider account.",
                429: "Provider quota or rate limit reached. Check your provider account before trying again.",
                400: "Provider rejected these inputs. Check the prompt and reference images.",
                404: "Provider model or job is unavailable. Check model access in your provider account.",
            }.get(response.status_code, "Provider request failed. It may have been accepted; check provider usage before trying again.")
            raise ProviderError(message)
        if response.is_redirect and not allow_redirect:
            raise ProviderError("Provider redirected the request to an unsupported location.")
        return response


def _json(response):
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        return result
    except ValueError:
        raise ProviderError("Provider returned an invalid response.") from None


class ComfyUIAdapter:
    id = "comfyui"
    managed_jobs = False

    async def submit_tool(self, **kwargs):
        # Retain Orange's backend selection, assets, mapping, and safe failover.
        from app.api.generation_v2 import generate_comfy
        return await generate_comfy(**kwargs)


class OpenAIAdapter:
    id = "openai"
    managed_jobs = True
    base = "https://api.openai.com/v1"

    def headers(self, key):
        return {"Authorization": f"Bearer {key}"}

    async def test(self, client, key):
        payload = _json(await _request(client, "GET", f"{self.base}/models", headers=self.headers(key)))
        if not isinstance(payload.get("data"), list):
            raise ProviderError("Provider returned an invalid model list.")
        return [item["id"] for item in payload["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)]

    async def submit(self, client, key, request):
        sizes = {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536"}
        body = {"model": request.model, "prompt": request.prompt, "size": sizes[request.aspect_ratio], "n": 1, "output_format": "png"}
        endpoint = "generations"
        if request.images:
            endpoint = "edits"
            body["images"] = [{"image_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"} for _, data, mime in request.images]
        payload = _json(await _request(client, "POST", f"{self.base}/images/{endpoint}", headers=self.headers(key), json=body))
        media = [Media(_decode(item.get("b64_json")), "image/png") for item in payload.get("data", []) if isinstance(item, dict)]
        if not media:
            raise ProviderError("Provider returned no image. The request may have been filtered.")
        return ProviderResult(media=media, usage=_usage(payload.get("usage")))


class GoogleAdapter:
    id = "google"
    managed_jobs = True
    resumable = True
    base = "https://generativelanguage.googleapis.com/v1beta"

    def headers(self, key):
        return {"x-goog-api-key": key, "Api-Revision": "2026-05-20"}

    async def test(self, client, key):
        models, seen, token = [], set(), None
        for _ in range(20):
            params = {"pageSize": 1000}
            if token:
                params["pageToken"] = token
            payload = _json(await _request(client, "GET", f"{self.base}/models", params=params, headers=self.headers(key)))
            if not isinstance(payload.get("models", []), list):
                raise ProviderError("Provider returned an invalid model list.")
            for item in payload.get("models", []):
                if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].startswith("models/"):
                    models.append(item["name"][len("models/"):])
            token = payload.get("nextPageToken")
            if not token:
                return models
            if not isinstance(token, str) or token in seen:
                break
            seen.add(token)
        raise ProviderError("Provider model listing could not be completed. Try testing the connection again.")

    async def submit(self, client, key, request):
        model = model_for(self.id, request.model)
        inputs = [{"type": "image", "data": base64.b64encode(data).decode("ascii"), "mime_type": mime} for _, data, mime in request.images]
        inputs.append({"type": "text", "text": request.prompt})
        output = {"type": model.output, "aspect_ratio": request.aspect_ratio}
        if model.output == "video":
            output.update(resolution=request.resolution, duration=f"{request.duration}s", delivery="uri")
        else:
            output["image_size"] = request.resolution
        payload = _json(await _request(client, "POST", f"{self.base}/interactions", headers=self.headers(key), json={
            "model": request.model, "input": inputs, "response_format": output, "store": False,
        }))
        # output_image/output_video are SDK conveniences, not REST fields.
        media = []
        remote_id = None
        for step in payload.get("steps", []):
            if step.get("type") != "model_output":
                continue
            for item in step.get("content", []):
                if item.get("type") != model.output:
                    continue
                if item.get("data"):
                    media.append(Media(_decode(item["data"]), item.get("mime_type", "image/png" if model.output == "image" else "video/mp4")))
                elif item.get("uri") and model.output == "video":
                    remote_id = self.file_id(item["uri"])
        if not media and not remote_id:
            raise ProviderError("Provider returned no media. The request may have been filtered.")
        return ProviderResult(media=media, remote_id=remote_id, usage=_usage(payload.get("usage")))

    @staticmethod
    def file_id(uri):
        # Never fetch an arbitrary provider URL or forward credentials to redirects.
        value = uri
        if isinstance(uri, str) and uri.startswith("https://generativelanguage.googleapis.com/"):
            parsed = urlsplit(uri)
            if parsed.netloc != "generativelanguage.googleapis.com" or parsed.query not in ("", "alt=media") or parsed.fragment or not parsed.path.startswith("/v1beta/"):
                raise ProviderError("Provider returned an unsupported media location.")
            value = parsed.path[len("/v1beta/"):]
            if value.endswith(":download"):
                value = value[:-len(":download")]
        if not isinstance(value, str) or not re.fullmatch(r"files/[A-Za-z0-9_-]{1,200}", value):
            raise ProviderError("Provider returned an unsupported media location.")
        return value

    async def poll(self, client, key, remote_id):
        name = self.file_id(remote_id)
        payload = _json(await _request(client, "GET", f"{self.base}/{name}", headers=self.headers(key)))
        if payload.get("state") == "FAILED":
            raise ProviderError("Provider could not finish processing the video.")
        if payload.get("state") != "ACTIVE":
            return ProviderResult(remote_id=name)
        url = f"{self.base}/{name}:download?alt=media"
        headers = self.headers(key)
        for _ in range(4):
            response = await _request(client, "GET", url, headers=headers, allow_redirect=True)
            if not response.is_redirect:
                break
            url = urljoin(url, response.headers.get("location", ""))
            parsed = urlsplit(url)
            trusted_host = parsed.hostname == "storage.googleapis.com" or (parsed.hostname or "").endswith(".googleusercontent.com")
            same_origin = parsed.hostname == "generativelanguage.googleapis.com"
            if parsed.scheme != "https" or parsed.port not in (None, 443) or parsed.username or parsed.password or not (trusted_host or same_origin):
                raise ProviderError("Provider returned an unsupported media location.")
            headers = self.headers(key) if same_origin else {}
        if response.status_code != 200:
            raise ProviderError("Provider could not return the video.")
        return ProviderResult(media=[Media(response.content, "video/mp4")])


class LazyAdapter:
    """Load the optional adapter implementation without circular module imports."""
    managed_jobs = True

    def __init__(self, provider):
        self.id = provider
        self.resumable = provider in {"xai", "runway", "fal"}

    def implementation(self):
        from app.core.media_aggregators import OpenRouterAdapter, VeniceAdapter
        from app.core.media_cloud import XAIAdapter, RunwayAdapter, FalAdapter
        return {"openrouter": OpenRouterAdapter, "venice": VeniceAdapter, "xai": XAIAdapter, "runway": RunwayAdapter, "fal": FalAdapter}[self.id]()

    async def test(self, client, key):
        return await self.implementation().test(client, key)

    async def submit(self, client, key, request):
        return await self.implementation().submit(client, key, request)

    async def poll(self, client, key, remote_id):
        return await self.implementation().poll(client, key, remote_id)

ADAPTERS = {adapter.id: adapter for adapter in (ComfyUIAdapter(), OpenAIAdapter(), GoogleAdapter(), *(LazyAdapter(p) for p in ("openrouter", "venice", "xai", "runway", "fal")))}


def adapter_for(tool):
    try:
        return ADAPTERS[tool.get("provider", "comfyui")]
    except (KeyError, TypeError):
        raise ValueError("Unsupported media provider.") from None
