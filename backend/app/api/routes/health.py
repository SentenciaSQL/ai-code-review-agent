from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.repositories.review_repository import ReviewRepository
from app.schemas.review import HealthResponse
from app.api.deps import get_repository

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application health",
    description="Reports process health and whether optional integrations are configured. It does not return secrets.",
)
def health(
    settings: Settings = Depends(get_settings),
    repository: ReviewRepository = Depends(get_repository),
) -> HealthResponse:
    database = "ok"
    try:
        repository.ping()
    except Exception:
        database = "error"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        app_name=settings.app_name,
        version=settings.app_version,
        database=database,  # type: ignore[arg-type]
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_configured=settings.llm_configured,
        github_token_configured=settings.github_token_configured,
        max_diff_bytes=settings.max_diff_bytes,
        max_diff_files=settings.max_diff_files,
        max_findings=settings.max_findings,
    )
