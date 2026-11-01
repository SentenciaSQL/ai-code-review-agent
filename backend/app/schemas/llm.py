from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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

_SEVERITY_ALIASES = {
    "critical": "critical",
    "blocker": "critical",
    "severe": "critical",
    "high": "high",
    "major": "high",
    "medium": "medium",
    "moderate": "medium",
    "low": "low",
    "minor": "low",
    "info": "low",
    "trivial": "low",
    "nit": "low",
}

_CATEGORY_ALIASES = {
    "bug": "bug",
    "bugs": "bug",
    "logic": "bug",
    "correctness": "bug",
    "defect": "bug",
    "security": "security",
    "vulnerability": "security",
    "security_vulnerability": "security",
    "performance": "performance",
    "error_handling": "error_handling",
    "error-handling": "error_handling",
    "errors": "error_handling",
    "exceptions": "error_handling",
    "exception_handling": "error_handling",
    "concurrency": "concurrency",
    "threading": "concurrency",
    "resource_management": "concurrency",
    "resources": "concurrency",
    "maintainability": "maintainability",
    "readability": "maintainability",
    "code_quality": "code_quality",
    "quality": "code_quality",
    "best_practices": "code_quality",
    "style": "code_quality",
}

_KIND_ALIASES = {
    "finding": "finding",
    "issue": "finding",
    "defect": "finding",
    "bug": "finding",
    "suggestion": "suggestion",
    "nit": "suggestion",
    "style": "suggestion",
    "question": "suggestion",
    "improvement": "suggestion",
}


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = str(value).replace("\x00", "")
    if not cleaned.strip():
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


class ModelFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    severity: Severity
    category: Category
    kind: FindingKind = "finding"
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    code_snippet: str | None = None
    recommended_fix: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    suggested_patch: str | None = None
    insufficient_context: bool = False

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, value: object) -> object:
        if isinstance(value, str):
            return _SEVERITY_ALIASES.get(value.strip().lower(), value.strip().lower())
        return value

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: object) -> object:
        if isinstance(value, str):
            key = value.strip().lower().replace(" ", "_")
            return _CATEGORY_ALIASES.get(key, key)
        return value

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_kind(cls, value: object) -> object:
        if value is None:
            return "finding"
        if isinstance(value, str):
            key = value.strip().lower()
            if not key:
                return "finding"
            return _KIND_ALIASES.get(key, key)
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip().rstrip("%")
            if not cleaned:
                return value
            value = float(cleaned)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 < float(value) <= 100:
            return float(value) / 100
        return value

    @field_validator("insufficient_context", mode="before")
    @classmethod
    def normalize_flag(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return value

    @field_validator("title", "explanation", "recommended_fix", mode="before")
    @classmethod
    def strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("file_path", "code_snippet", "suggested_patch", mode="before")
    @classmethod
    def empty_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def clean_fields(self) -> ModelFinding:
        self.title = _clip(self.title, 200) or "Untitled finding"
        self.explanation = _clip(self.explanation, 4000) or self.explanation
        self.recommended_fix = _clip(self.recommended_fix, 4000) or self.recommended_fix
        self.file_path = _clip(self.file_path, 500)
        self.code_snippet = _clip(self.code_snippet, 2000)
        self.suggested_patch = _clip(self.suggested_patch, 4000)
        if self.line_start is not None and self.line_start < 1:
            self.line_start = None
        if self.line_end is not None and self.line_end < 1:
            self.line_end = None
        if self.line_start is None:
            self.line_end = None
        elif self.line_end is None:
            self.line_end = self.line_start
        elif self.line_end < self.line_start:
            self.line_start, self.line_end = self.line_end, self.line_start
        if self.severity == "low" and self.kind == "finding" and self.confidence < 0.45:
            self.kind = "suggestion"
        return self


class ModelReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    context_limitations: str | None = None
    findings: list[ModelFinding] = Field(default_factory=list)

    @field_validator("summary", mode="before")
    @classmethod
    def clean_summary(cls, value: object) -> object:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("context_limitations", mode="before")
    @classmethod
    def clean_limitations(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value
