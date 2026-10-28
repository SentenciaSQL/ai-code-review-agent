from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class FindingRecord:
    id: str
    review_id: str
    title: str
    explanation: str
    severity: str
    category: str
    kind: str
    file_path: str | None
    line_start: int | None
    line_end: int | None
    code_snippet: str | None
    recommended_fix: str
    confidence: float
    suggested_patch: str | None
    insufficient_context: bool
    position: int


@dataclass(slots=True)
class ReviewRecord:
    id: str
    title: str
    source_type: str
    source_ref: str | None
    status: str
    summary: str | None
    context_limitations: str | None
    provider: str | None
    model: str | None
    prompt_version: str | None
    error_message: str | None
    metadata: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    findings: list[FindingRecord] = field(default_factory=list)


@dataclass(slots=True)
class SeverityCounts:
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "critical": self.critical,
            "high": self.high,
            "medium": self.medium,
            "low": self.low,
        }


@dataclass(slots=True)
class ReviewListItem:
    review: ReviewRecord
    finding_count: int
    suggestion_count: int
    severity_counts: SeverityCounts


@dataclass(slots=True)
class DashboardStats:
    total_reviews: int
    completed_reviews: int
    failed_reviews: int
    processing_reviews: int
    total_findings: int
    total_suggestions: int
    findings_by_severity: SeverityCounts
    findings_by_category: dict[str, int]
