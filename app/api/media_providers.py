"""Authenticated provider management and semantic cloud submission."""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from io import BytesIO
from PIL import Image

from app.api.admin import verify_admin
from app.api.generate import MAX_UPLOAD_BYTES, _read_validated_image
from app.core import media_provider_config as config
from app.core.media_providers import ADAPTERS, ModelDiscovery, MediaRequest, ProviderError, provider_models, validate_api_tool
from app.core.media_jobs import job_manager

router = APIRouter()


@router.get("/api/admin/credentials/civitai")
def civitai_status(_=Depends(verify_admin)):
    from app.core import civitai
    try:
        return civitai.token_status()
    except OSError:
        raise HTTPException(503, "Could not access the server credential store. Configure CIVITAI_API_KEY or unlock the native credential store.") from None


@router.put("/api/admin/credentials/civitai")
def save_civitai(payload: dict, _=Depends(verify_admin)):
    from app.core import civitai
    try:
        civitai.save_token(payload.get("apiKey"))
        return {"status": "saved"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except OSError:
        raise HTTPException(503, "Could not save the Civitai credential in the native credential store.") from None


@router.delete("/api/admin/credentials/civitai")
def clear_civitai(_=Depends(verify_admin)):
    from app.core import civitai
    try:
        civitai.clear_token()
        return {"status": "removed"}
    except OSError:
        raise HTTPException(503, "Could not remove the Civitai credential.") from None


@router.post("/api/admin/credentials/civitai/test")
async def test_civitai(_=Depends(verify_admin)):
    from app.core import civitai
    try:
        headers = civitai.auth_headers("https://civitai.com/api/v1/me")
        if not headers:
            raise HTTPException(400, "Save a Civitai credential first.")
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get("https://civitai.com/api/v1/me", headers=headers)
        if response.status_code != 200:
            raise HTTPException(502, "Civitai could not verify this credential. Check the key and account access.")
        return {"status": "connected"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Could not test the Civitai credential.") from None


async def _reference_image(upload):
    _, raw, _ = await _read_validated_image(upload)
    # All supported APIs accept PNG. Normalize MIME, animated references and
    # metadata before transmission rather than forwarding arbitrary image tags.
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 40_000_000:
                raise ValueError("Reference image is too large.")
            clean = Image.new("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB", image.size)
            clean.paste(image)
            buffer = BytesIO()
            clean.save(buffer, "PNG")
            data = buffer.getvalue()
    except (OSError, Image.DecompressionBombError):
        raise ValueError("Reference image could not be prepared.") from None
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Prepared reference image exceeds the upload limit.")
    return "reference.png", data, "image/png"


@router.get("/api/admin/providers")
def providers(_=Depends(verify_admin)):
    return {"providers": config.public_settings()}


@router.put("/api/admin/providers/{provider}")
def update_provider(provider: str, payload: dict, _=Depends(verify_admin)):
    try:
        config.save_provider(provider, payload)
        return {"status": "saved"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except OSError:
        raise HTTPException(503, "Could not save the provider credential or settings. Check the server's native credential store or use an environment variable.") from None


@router.post("/api/admin/providers/{provider}/test")
async def test_provider(provider: str, _=Depends(verify_admin)):
    try:
        if provider not in config.ENV_KEYS:
            raise ValueError("Unknown API provider.")
        key = config.credential(provider)
        if not key:
            raise ValueError("Save a credential or configure an environment variable first.")
        if provider == "anthropic":
            from app.core.llm import list_llm_models
            await list_llm_models("anthropic", None, key)
            return {"status": "connected", "models": [], "detail": "Connected to Anthropic. Select a text model under Prompt Enhancement."}
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            model_ids = await ADAPTERS[provider].test(client, key)
        if isinstance(model_ids, ModelDiscovery):
            available = config.save_discovery(provider, [m.id for m in model_ids.models], key, definitions=model_ids.models)
        else:
            available = config.save_discovery(provider, model_ids, key)
        names = {model.id: model.name for model in provider_models(provider)}
        detail = ('Connected to Runway. Choose from Orange’s curated models when creating a tool; model access is checked when generating.' if provider == 'runway' else
                  f'Connected. Found {len(available)} compatible media model(s). Choose a model when creating a tool.' if available else
                  'Connected. This account lists no media models currently supported by Orange.')
        return {"status": "connected", "models": [{"id": value, "name": names[value]} for value in available],
                "detail": detail}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from None
    except Exception:
        raise HTTPException(503, "Could not test this provider. Check the credential store and provider availability.") from None


async def submit_api_tool(request, tool, prompt, aspect_ratio, resolution, duration, image, image2):
    try:
        model = validate_api_tool(tool)
        provider = tool["provider"]
        if not config.ready(provider, model.id):
            raise HTTPException(503, "This tool's API provider is not configured or is disabled. Contact the administrator.")
        settings = tool["api"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Prompt is required for this tool.")
        ratio = aspect_ratio or settings["ratios"][0]
        resolution = resolution if isinstance(resolution, str) else settings["defaultResolution"]
        if ratio not in settings["ratios"] or resolution not in settings["resolutions"]:
            raise ValueError("Choose one of this tool's aspect ratios and resolutions.")
        seconds = duration if isinstance(duration, (int, float)) else settings.get("defaultDuration")
        if model.output == "video":
            if seconds not in settings["durations"]:
                raise ValueError("Choose one of this tool's video durations.")
            seconds = int(seconds)
        elif seconds is not None:
            raise ValueError("Image tools do not accept video duration.")
        uploads = [item for item in (image, image2) if item is not None]
        if len(uploads) > settings.get("references", 0):
            raise ValueError("This tool does not support that many reference images.")
        if settings.get("requireImage") and not image:
            raise ValueError("An image is required for this editing tool.")
        images = [await _reference_image(item) for item in uploads]
        instructions = settings.get("systemPrompt", "").strip()
        generation_prompt = f"{instructions}\n\nUser request:\n{prompt.strip()}" if instructions else prompt.strip()
        if len(generation_prompt) > model.prompt_limit:
            raise ValueError(f'Prompt and tool instructions must fit within {model.prompt_limit} characters for this model.')
        semantic = MediaRequest(model.id, generation_prompt, ratio, resolution, seconds, images)
        return job_manager.submit(provider, model, tool["id"], semantic, request.client.host if request.client else "unknown")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
