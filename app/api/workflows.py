from fastapi import APIRouter

from app.core.config import load_config
from app.core.public_config import build_public_config

router = APIRouter()


@router.get("/api/workflows")
def get_workflows():
    # Never hand the browser a config-shaped object. The admin configuration can
    # grow secrets/operational fields without accidentally exposing them here.
    return build_public_config(load_config())
