from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_repository, get_review_service
from app.core.exceptions import AppError
from app.repositories.review_repository import ReviewRepository
from app.schemas.review import (
    DashboardStatsResponse,
    DiffReviewCreate,
    ErrorResponse,
    GitHubReviewCreate,
    ReviewDetailResponse,
    ReviewListResponse,
    review_to_detail,
    review_to_summary,
    stats_to_response,
)
from app.services.export_service import render_json, render_markdown
from app.services.review_service import ReviewService

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post(
    "/diff",
    response_model=ReviewDetailResponse,
    responses={422: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
    summary="Review a Git diff",
)
def review_diff(
    payload: DiffReviewCreate,
    service: ReviewService = Depends(get_review_service),
) -> ReviewDetailResponse:
    return service.create_from_diff(payload.title, payload.diff)


@router.post(
    "/github",
    response_model=ReviewDetailResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    summary="Review a GitHub pull request",
)
def review_github(
    payload: GitHubReviewCreate,
    service: ReviewService = Depends(get_review_service),
) -> ReviewDetailResponse:
    return service.create_from_github(
        payload.title,
        payload.repository_url,
        payload.pull_request_number,
    )


@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Review statistics",
    description="Counts are computed from reviews stored in the local database.",
)
def review_stats(repository: ReviewRepository = Depends(get_repository)) -> DashboardStatsResponse:
    return stats_to_response(repository.stats())


@router.get(
    "",
    response_model=ReviewListResponse,
    summary="List stored reviews",
)
def list_reviews(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: ReviewRepository = Depends(get_repository),
) -> ReviewListResponse:
    items, total = repository.list_reviews(limit=limit, offset=offset)
    return ReviewListResponse(
        items=[review_to_summary(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{review_id}/export",
    summary="Export a review as JSON or Markdown",
    responses={404: {"model": ErrorResponse}},
)
def export_review(
    review_id: str,
    export_format: Literal["json", "markdown"] = Query(alias="format", default="json"),
    repository: ReviewRepository = Depends(get_repository),
) -> Response:
    review = repository.get(review_id)
    if review is None:
        raise AppError("Review not found.", status_code=404, code="review_not_found")
    detail = review_to_detail(review)
    if export_format == "markdown":
        body = render_markdown(detail)
        media_type = "text/markdown; charset=utf-8"
        extension = "md"
    else:
        body = render_json(detail)
        media_type = "application/json"
        extension = "json"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="patchline-{review_id}.{extension}"'},
    )


@router.get(
    "/{review_id}",
    response_model=ReviewDetailResponse,
    summary="Get one review",
    responses={404: {"model": ErrorResponse}},
)
def get_review(
    review_id: str,
    repository: ReviewRepository = Depends(get_repository),
) -> ReviewDetailResponse:
    review = repository.get(review_id)
    if review is None:
        raise AppError("Review not found.", status_code=404, code="review_not_found")
    return review_to_detail(review)


@router.delete(
    "/{review_id}",
    status_code=204,
    summary="Delete a review",
    responses={404: {"model": ErrorResponse}},
)
def delete_review(
    review_id: str,
    repository: ReviewRepository = Depends(get_repository),
) -> Response:
    if not repository.delete(review_id):
        raise AppError("Review not found.", status_code=404, code="review_not_found")
    return Response(status_code=204)
