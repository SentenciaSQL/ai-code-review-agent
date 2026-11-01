from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.review import DashboardStats, FindingRecord, ReviewListItem, ReviewRecord

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal[
    "bug",
    "security",
    "performance",
    "error_handling",
    "concurrency",
    "maintainability",
    "code_quality",
]
FindingKind = Literal["finding", "suggestion"]
ReviewStatus = Literal["processing", "completed", "failed"]
SourceType = Literal["diff", "github"]


class DiffReviewCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    diff: str = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("diff")
    @classmethod
    def clean_diff(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Diff content is empty.")
        return value


class GitHubReviewCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    repository_url: str = Field(min_length=1, max_length=500)
    pull_request_number: int | None = Field(default=None, ge=1)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("repository_url")
    @classmethod
    def clean_url(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Enter a GitHub repository or pull request URL.")
        return cleaned


class SeverityCountResponse(BaseModel):
    critical: int
    high: int
    medium: int
    low: int


class FindingResponse(BaseModel):
    id: str
    title: str
    explanation: str
    severity: Severity
    category: Category
    kind: FindingKind
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    code_snippet: str | None = None
    recommended_fix: str
    confidence: float = Field(ge=0, le=1)
    suggested_patch: str | None = None
    insufficient_context: bool = False


class ReviewFileResponse(BaseModel):
    path: str
    status: str
    additions: int = 0
    deletions: int = 0
    binary: bool = False
    omitted: bool = False


class PullRequestResponse(BaseModel):
    owner: str
    repo: str
    number: int
    url: str
    title: str
    head_sha: str | None = None
    base_ref: str | None = None
    author: str | None = None


class UsageResponse(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class ReviewMetadataResponse(BaseModel):
    prompt_version: str | None = None
    files: list[ReviewFileResponse] = Field(default_factory=list)
    pull_request: PullRequestResponse | None = None
    usage: UsageResponse | None = None
    omitted_files: list[str] = Field(default_factory=list)


class ReviewSummaryResponse(BaseModel):
    id: str
    title: str
    source_type: SourceType
    source_ref: str | None = None
    status: ReviewStatus
    summary: str | None = None
    finding_count: int
    suggestion_count: int
    severity_counts: SeverityCountResponse
    provider: str | None = None
    model: str | None = None
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class ReviewListResponse(BaseModel):
    items: list[ReviewSummaryResponse]
    total: int
    limit: int
    offset: int


class ReviewDetailResponse(BaseModel):
    id: str
    title: str
    source_type: SourceType
    source_ref: str | None = None
    status: ReviewStatus
    summary: str | None = None
    context_limitations: str | None = None
    findings: list[FindingResponse]
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    error_message: str | None = None
    metadata: ReviewMetadataResponse
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class DashboardStatsResponse(BaseModel):
    total_reviews: int
    completed_reviews: int
    failed_reviews: int
    processing_reviews: int
    total_findings: int
    total_suggestions: int
    findings_by_severity: SeverityCountResponse
    findings_by_category: dict[str, int]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["ok", "degraded"]
    app_name: str
    version: str
    database: Literal["ok", "error"]
    llm_provider: str
    llm_model: str
    llm_configured: bool
    github_token_configured: bool
    max_diff_bytes: int
    max_diff_files: int
    max_findings: int


class ErrorResponse(BaseModel):
    detail: str
    code: str
    review_id: str | None = None


def _metadata_response(metadata: dict) -> ReviewMetadataResponse:
    files = []
    for item in metadata.get("files") or []:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        files.append(
            ReviewFileResponse(
                path=str(item.get("path")),
                status=str(item.get("status") or "modified"),
                additions=int(item.get("additions") or 0),
                deletions=int(item.get("deletions") or 0),
                binary=bool(item.get("binary")),
                omitted=bool(item.get("omitted")),
            )
        )
    pull_request = None
    raw_pr = metadata.get("pull_request")
    if isinstance(raw_pr, dict) and raw_pr.get("owner") and raw_pr.get("repo"):
        pull_request = PullRequestResponse(
            owner=str(raw_pr["owner"]),
            repo=str(raw_pr["repo"]),
            number=int(raw_pr.get("number") or 0),
            url=str(raw_pr.get("url") or ""),
            title=str(raw_pr.get("title") or ""),
            head_sha=raw_pr.get("head_sha"),
            base_ref=raw_pr.get("base_ref"),
            author=raw_pr.get("author"),
        )
    usage = None
    raw_usage = metadata.get("usage")
    if isinstance(raw_usage, dict):
        usage = UsageResponse(
            prompt_tokens=raw_usage.get("prompt_tokens"),
            completion_tokens=raw_usage.get("completion_tokens"),
        )
    omitted = [str(item) for item in metadata.get("omitted_files") or []]
    return ReviewMetadataResponse(
        prompt_version=metadata.get("prompt_version"),
        files=files,
        pull_request=pull_request,
        usage=usage,
        omitted_files=omitted,
    )


def _finding_response(finding: FindingRecord) -> FindingResponse:
    return FindingResponse(
        id=finding.id,
        title=finding.title,
        explanation=finding.explanation,
        severity=finding.severity,  # type: ignore[arg-type]
        category=finding.category,  # type: ignore[arg-type]
        kind=finding.kind,  # type: ignore[arg-type]
        file_path=finding.file_path,
        line_start=finding.line_start,
        line_end=finding.line_end,
        code_snippet=finding.code_snippet,
        recommended_fix=finding.recommended_fix,
        confidence=finding.confidence,
        suggested_patch=finding.suggested_patch,
        insufficient_context=finding.insufficient_context,
    )


def review_to_summary(item: ReviewListItem) -> ReviewSummaryResponse:
    review = item.review
    return ReviewSummaryResponse(
        id=review.id,
        title=review.title,
        source_type=review.source_type,  # type: ignore[arg-type]
        source_ref=review.source_ref,
        status=review.status,  # type: ignore[arg-type]
        summary=review.summary,
        finding_count=item.finding_count,
        suggestion_count=item.suggestion_count,
        severity_counts=SeverityCountResponse(**item.severity_counts.as_dict()),
        provider=review.provider,
        model=review.model,
        created_at=review.created_at,
        updated_at=review.updated_at,
        error_message=review.error_message,
    )


def review_to_detail(review: ReviewRecord) -> ReviewDetailResponse:
    return ReviewDetailResponse(
        id=review.id,
        title=review.title,
        source_type=review.source_type,  # type: ignore[arg-type]
        source_ref=review.source_ref,
        status=review.status,  # type: ignore[arg-type]
        summary=review.summary,
        context_limitations=review.context_limitations,
        findings=[_finding_response(finding) for finding in review.findings],
        provider=review.provider,
        model=review.model,
        prompt_version=review.prompt_version,
        error_message=review.error_message,
        metadata=_metadata_response(review.metadata),
        created_at=review.created_at,
        updated_at=review.updated_at,
        completed_at=review.completed_at,
    )


def stats_to_response(stats: DashboardStats) -> DashboardStatsResponse:
    return DashboardStatsResponse(
        total_reviews=stats.total_reviews,
        completed_reviews=stats.completed_reviews,
        failed_reviews=stats.failed_reviews,
        processing_reviews=stats.processing_reviews,
        total_findings=stats.total_findings,
        total_suggestions=stats.total_suggestions,
        findings_by_severity=SeverityCountResponse(**stats.findings_by_severity.as_dict()),
        findings_by_category=stats.findings_by_category,
    )
