import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.api.admin import verify_admin
from app.core.config import get_system_prompt, get_tool_settings, load_config
from app.core.llm import LLMConfigError, LLMError, call_llm, list_llm_models
from app.core.rate_limit import SlidingWindowRateLimiter

router = APIRouter()

MAX_PROMPT_CHARS = int(os.environ.get("ORANGE_MAX_PROMPT_CHARS", "10000"))
ENHANCEMENT_LIMITER = SlidingWindowRateLimiter()


def _rate_limit_per_minute() -> int:
    try:
        return max(0, int(os.environ.get("ORANGE_LLM_RATE_LIMIT_PER_MINUTE", "30")))
    except (TypeError, ValueError):
        return 30


def _log_llm_error(context: str, exc: LLMError) -> None:
    print(f"{context}: {exc.technical_message}")


def _resolve_tool_llm(tool_id: str):
    tool = get_tool_settings(tool_id)
    if not tool:
        raise HTTPException(status_code=400, detail="Invalid tool ID")

    mapping = tool.get("nodeMapping", {}) if isinstance(tool.get("nodeMapping"), dict) else {}
    if not mapping.get("prompt"):
        raise HTTPException(
            status_code=400,
            detail="Prompt enhancement is not supported for this tool.",
        )

    config = load_config()
    global_llm = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
    tool_enhance = tool.get("promptEnhance", {}) if isinstance(tool.get("promptEnhance"), dict) else {}

    if not global_llm.get("enabled", False):
        raise HTTPException(status_code=400, detail="Prompt enhancement is disabled globally.")
    if tool_enhance.get("enabled", True) is False:
        raise HTTPException(status_code=400, detail="Prompt enhancement is disabled for this tool.")

    def resolved(name: str, default=None):
        value = tool_enhance.get(name)
        if value not in (None, ""):
            return value
        return global_llm.get(name, default)

    return {
        "provider": resolved("provider", "openai"),
        "base_url": resolved("baseUrl"),
        "api_key": resolved("apiKey"),
        "model": resolved("model"),
        "system_prompt": get_system_prompt(tool_id),
    }


@router.post("/api/enhance-prompt")
async def enhance_prompt(
    request: Request,
    prompt: str = Form(...),
    tool_id: str = Form(...),
):
    if len(prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail=f"Prompt exceeds the {MAX_PROMPT_CHARS} character limit.")

    client_ip = request.client.host if request.client else "unknown"
    if not ENHANCEMENT_LIMITER.allow(
        client_ip,
        _rate_limit_per_minute(),
        window_seconds=60.0,
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many prompt enhancement requests. Try again shortly.",
        )

    settings = _resolve_tool_llm(tool_id)
    try:
        enhanced = await call_llm(
            provider=settings["provider"],
            base_url=settings["base_url"],
            api_key=settings["api_key"],
            model=settings["model"],
            system_prompt=settings["system_prompt"],
            prompt=prompt,
        )
        return {"enhanced_prompt": enhanced}
    except LLMConfigError as exc:
        _log_llm_error(f"Prompt enhancement configuration error for tool {tool_id}", exc)
        raise HTTPException(status_code=400, detail=exc.public_message)
    except LLMError as exc:
        _log_llm_error(f"Prompt enhancement provider error for tool {tool_id}", exc)
        raise HTTPException(status_code=exc.status_code, detail=exc.public_message)
    except Exception as exc:
        print(f"Unexpected prompt enhancement error for tool {tool_id}: {type(exc).__name__}")
        raise HTTPException(status_code=500, detail="Prompt enhancement failed.")


@router.post("/api/admin/llm/models")
async def get_llm_models(payload: dict, _=Depends(verify_admin)):
    provider = payload.get("provider", "") if isinstance(payload, dict) else ""
    base_url = payload.get("baseUrl") if isinstance(payload, dict) else None
    api_key = payload.get("apiKey") if isinstance(payload, dict) else None

    try:
        models = await list_llm_models(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
        )
        return {"models": models}
    except LLMConfigError as exc:
        _log_llm_error("LLM model-list configuration error", exc)
        raise HTTPException(status_code=400, detail=exc.public_message)
    except LLMError as exc:
        _log_llm_error("LLM model-list provider error", exc)
        raise HTTPException(status_code=exc.status_code, detail=exc.public_message)
    except Exception as exc:
        print(f"Unexpected LLM model-list error: {type(exc).__name__}")
        raise HTTPException(status_code=500, detail="Failed to fetch prompt enhancement models.")
