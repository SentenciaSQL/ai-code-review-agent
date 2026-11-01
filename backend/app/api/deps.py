from __future__ import annotations

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.providers.openai_compatible import build_provider
from app.repositories.review_repository import ReviewRepository
from app.services.github_service import GitHubService
from app.services.review_service import ReviewService


def get_repository(settings: Settings = Depends(get_settings)) -> ReviewRepository:
    return ReviewRepository(settings.resolved_database_path)


def get_review_service(
    settings: Settings = Depends(get_settings),
    repository: ReviewRepository = Depends(get_repository),
) -> ReviewService:
    return ReviewService(
        settings=settings,
        repository=repository,
        provider=build_provider(settings),
        github=GitHubService(settings),
    )
