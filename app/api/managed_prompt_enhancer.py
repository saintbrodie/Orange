from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import verify_admin
from app.core.llm import LLMConfigError, LLMError, call_llm
from app.core.managed_prompt_enhancer import (
    MANAGED_MODEL_ID,
    get_status,
    remove_installation,
    schedule_install,
)

router = APIRouter()


@router.get("/api/admin/prompt-enhancer/managed/status")
def managed_prompt_enhancer_status(_=Depends(verify_admin)):
    return get_status()


@router.post("/api/admin/prompt-enhancer/managed/install")
def install_managed_prompt_enhancer(_=Depends(verify_admin)):
    try:
        return schedule_install()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/admin/prompt-enhancer/managed/remove")
def remove_managed_prompt_enhancer(_=Depends(verify_admin)):
    return remove_installation()


@router.post("/api/admin/prompt-enhancer/managed/test")
async def test_managed_prompt_enhancer(_=Depends(verify_admin)):
    try:
        text = await call_llm(
            provider="managed",
            base_url=None,
            api_key=None,
            model=MANAGED_MODEL_ID,
            system_prompt="Reply with exactly: Orange local prompt enhancement is ready.",
            prompt="Run the readiness check.",
        )
        return {"ok": True, "response": text}
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=exc.public_message)
    except LLMError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.public_message)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
