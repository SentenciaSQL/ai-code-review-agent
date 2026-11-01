from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.core.exceptions import LLMResponseError
from app.schemas.llm import ModelFinding, ModelReviewResponse

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def parse_model_payload(content: str, *, max_findings: int) -> ModelReviewResponse:
    try:
        payload = _load_json(content)
        parsed = ModelReviewResponse.model_validate(payload)
    except (LLMResponseError, ValidationError) as exc:
        message = str(exc) if isinstance(exc, LLMResponseError) else _validation_message(exc)
        raise LLMResponseError(message) from exc

    findings = _dedupe(parsed.findings)
    findings.sort(
        key=lambda item: (
            -_SEVERITY_RANK.get(item.severity, 0),
            -item.confidence,
            item.file_path or "",
            item.line_start or 0,
            item.title,
        )
    )
    dropped = 0
    if len(findings) > max_findings:
        dropped = len(findings) - max_findings
        findings = findings[:max_findings]

    limitations = parsed.context_limitations
    if dropped:
        note = f"{dropped} additional model items were omitted because MAX_FINDINGS is {max_findings}."
        limitations = f"{limitations}\n{note}" if limitations else note

    summary = parsed.summary.strip()
    if not summary:
        actionable = sum(1 for item in findings if item.kind == "finding")
        suggestions = sum(1 for item in findings if item.kind == "suggestion")
        summary = (
            f"The review finished with {actionable} findings and {suggestions} suggestions. "
            "The model did not provide a separate narrative summary."
        )

    return ModelReviewResponse(summary=summary, context_limitations=limitations, findings=findings)


def _load_json(content: str) -> object:
    text = content.strip()
    if text.startswith("```"):
        text = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise LLMResponseError("The model did not return valid JSON.") from exc
        raise LLMResponseError("The model did not return valid JSON.")


def _validation_message(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors()[:8]:
        location = ".".join(str(item) for item in error.get("loc", []))
        message = str(error.get("msg", "invalid"))
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts) or "The model response did not match the review schema."


def _dedupe(findings: list[ModelFinding]) -> list[ModelFinding]:
    selected: dict[tuple[str, int | None, str, str], ModelFinding] = {}
    order: list[tuple[str, int | None, str, str]] = []
    for finding in findings:
        key = (
            (finding.file_path or "").lower(),
            finding.line_start,
            finding.category,
            " ".join(finding.title.lower().split()),
        )
        current = selected.get(key)
        if current is None:
            selected[key] = finding
            order.append(key)
            continue
        current_rank = (_SEVERITY_RANK.get(current.severity, 0), current.confidence)
        next_rank = (_SEVERITY_RANK.get(finding.severity, 0), finding.confidence)
        if next_rank > current_rank:
            selected[key] = finding
    return [selected[key] for key in order]
