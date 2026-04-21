"""Health check endpoint."""

from fastapi import APIRouter

from tik_core import __version__
from tik_core.config import get_settings
from tik_core.storage.schemas import HealthOut

router = APIRouter()


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Health check basique. Pas d'auth requise."""
    settings = get_settings()
    return HealthOut(status="ok", version=__version__, env=settings.env)
