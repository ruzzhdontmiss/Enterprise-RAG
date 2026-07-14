"""Health check endpoints.

Used by Docker Compose healthchecks, load balancers, and CI smoke tests.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_env: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness check. Does not verify downstream dependencies (DB, Qdrant,
    Mistral) — that will be added as a separate /health/ready endpoint once
    those clients exist (Phase 1+).
    """
    settings = get_settings()
    return HealthResponse(status="ok", app_env=settings.app_env)
