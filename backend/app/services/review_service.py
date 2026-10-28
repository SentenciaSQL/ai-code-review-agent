from __future__ import annotations

import logging
import time
import uuid

from app.core.config import Settings
from app.core.exceptions import AppError, LLMProviderError, LLMResponseError
from app.core.redaction import redact
from app.models.review import FindingRecord
from app.prompts.review_v1 import (
    PROMPT_VERSION,
    REPAIR_SYSTEM_PROMPT,
    build_repair_prompt,
    build_system_prompt,
    build_user_prompt,
)
from app.providers.base import LLMCompletion, LLMProvider
from app.repositories.review_repository import ReviewRepository
from app.schemas.llm import ModelFinding, ModelReviewResponse
from app.schemas.review import ReviewDetailResponse, review_to_detail
from app.services.diff_parser import (
    DiffParseError,
    ParsedDiff,
    new_line_index,
    parse_unified_diff,
    render_annotated_diff,
)
from app.services.github_service import GitHubReviewSource, GitHubService, parse_github_reference
from app.services.llm_response import parse_model_payload

logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(
        self,
        settings: Settings,
        repository: ReviewRepository,
        provider: LLMProvider,
        github: GitHubService,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._provider = provider
        self._github = github

    def create_from_diff(self, title: str | None, diff: str) -> ReviewDetailResponse:
        parsed = self._parse(diff)
        annotated = render_annotated_diff(parsed)
        self._ensure_limits(diff, parsed, annotated)
        self._ensure_llm_ready()
        limitations = self._prior_limitations(parsed, None)
        review_id = str(uuid.uuid4())
        self._repository.create(
            review_id=review_id,
            title=_diff_title(title, parsed),
            source_type="diff",
            source_ref=None,
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            prompt_version=PROMPT_VERSION,
            metadata=self._metadata(parsed, None, limitations),
        )
        logger.info("Review %s created source=diff", review_id)
        return self._run(
            review_id,
            parsed,
            annotated,
            limitations,
            source_label="pasted diff",
        )

    def create_from_github(
        self,
        title: str | None,
        repository_url: str,
        pull_request_number: int | None,
    ) -> ReviewDetailResponse:
        parse_github_reference(
            repository_url,
            pull_request_number,
            web_host=self._settings.github_web_host,
        )
        self._ensure_llm_ready()
        source = self._github.fetch_pull_request(repository_url, pull_request_number)
        parsed = self._parse(source.diff)
        annotated = render_annotated_diff(parsed)
        self._ensure_limits(source.diff, parsed, annotated)
        limitations = self._prior_limitations(parsed, source)
        review_id = str(uuid.uuid4())
        display_title = (title or source.title).strip()[:200] or f"{source.owner}/{source.repo}#{source.number}"
        self._repository.create(
            review_id=review_id,
            title=display_title,
            source_type="github",
            source_ref=f"{source.owner}/{source.repo}#{source.number}",
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            prompt_version=PROMPT_VERSION,
            metadata=self._metadata(parsed, source, limitations),
        )
        logger.info("Review %s created source=github ref=%s/%s#%s", review_id, source.owner, source.repo, source.number)
        return self._run(
            review_id,
            parsed,
            annotated,
            limitations,
            source_label=f"GitHub pull request {source.owner}/{source.repo}#{source.number}",
        )

    def _run(
        self,
        review_id: str,
        parsed: ParsedDiff,
        annotated: str,
        limitations: list[str],
        *,
        source_label: str,
    ) -> ReviewDetailResponse:
        started = time.perf_counter()
        try:
            reviewed, completion = self._analyze(
                annotated=annotated,
                parsed=parsed,
                limitations=limitations,
                source_label=source_label,
            )
            findings = self._to_records(review_id, reviewed.findings, parsed)
            stored = self._repository.complete(
                review_id,
                summary=reviewed.summary,
                context_limitations=reviewed.context_limitations,
                findings=findings,
                model=completion.model,
                usage={
                    "prompt_tokens": completion.prompt_tokens,
                    "completion_tokens": completion.completion_tokens,
                },
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Review %s completed findings=%s duration_ms=%s",
                review_id,
                len(findings),
                elapsed_ms,
            )
            return review_to_detail(stored)
        except AppError as exc:
            if exc.review_id is None:
                self._repository.mark_failed(review_id, exc.message)
                raise AppError(
                    exc.message,
                    status_code=exc.status_code,
                    code=exc.code,
                    review_id=review_id,
                ) from exc
            raise
        except Exception as exc:
            logger.exception("Review %s failed unexpectedly", review_id)
            message = "The review failed because of an unexpected server error."
            self._repository.mark_failed(review_id, message)
            raise AppError(message, status_code=500, code="internal_error", review_id=review_id) from exc

    def _analyze(
        self,
        *,
        annotated: str,
        parsed: ParsedDiff,
        limitations: list[str],
        source_label: str,
    ) -> tuple[ModelReviewResponse, LLMCompletion]:
        text_files = sum(1 for item in parsed.files if not item.is_binary and item.hunks)
        binary_files = sum(1 for item in parsed.files if item.is_binary)
        system_prompt = build_system_prompt(self._settings.max_findings)
        user_prompt = build_user_prompt(
            source_label=source_label,
            annotated_diff=annotated,
            text_files=text_files,
            binary_files=binary_files,
            additions=parsed.additions,
            deletions=parsed.deletions,
            prior_limitations=limitations,
        )
        try:
            completion = self._provider.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        except LLMProviderError as exc:
            raise AppError(redact(str(exc)), status_code=502, code="llm_provider_error") from exc

        try:
            reviewed = self._parse_completion(completion)
        except LLMResponseError as first_error:
            logger.warning("Model response failed validation; attempting one structural repair")
            try:
                repaired = self._provider.complete(
                    system_prompt=REPAIR_SYSTEM_PROMPT,
                    user_prompt=build_repair_prompt(completion.content, str(first_error)),
                )
            except LLMProviderError as exc:
                raise AppError(redact(str(exc)), status_code=502, code="llm_provider_error") from exc
            try:
                reviewed = self._parse_completion(repaired)
            except LLMResponseError as exc:
                raise AppError(
                    "The model returned a response that did not match the review schema, "
                    "and a single repair attempt also failed. No findings were invented.",
                    status_code=502,
                    code="llm_response_invalid",
                ) from exc
            completion = LLMCompletion(
                content=repaired.content,
                model=repaired.model,
                prompt_tokens=_add(completion.prompt_tokens, repaired.prompt_tokens),
                completion_tokens=_add(completion.completion_tokens, repaired.completion_tokens),
                finish_reason=repaired.finish_reason,
            )
        merged_limitations = _merge_limitations(limitations, reviewed.context_limitations)
        return (
            ModelReviewResponse(
                summary=reviewed.summary,
                context_limitations=merged_limitations,
                findings=reviewed.findings,
            ),
            completion,
        )

    def _parse_completion(self, completion: LLMCompletion) -> ModelReviewResponse:
        try:
            return parse_model_payload(completion.content, max_findings=self._settings.max_findings)
        except LLMResponseError as exc:
            if completion.finish_reason == "length":
                raise LLMResponseError(
                    "The model output was truncated before the review JSON completed. "
                    "Raise LLM_MAX_OUTPUT_TOKENS or lower MAX_FINDINGS. "
                    + str(exc)
                ) from exc
            raise

    def _ensure_llm_ready(self) -> None:
        if self._settings.llm_provider != "openai_compatible":
            raise AppError(
                "Unsupported LLM_PROVIDER. Set LLM_PROVIDER=openai_compatible.",
                status_code=503,
                code="llm_not_configured",
            )
        if not self._settings.llm_model or not self._settings.llm_base_url:
            raise AppError(
                "The language model is not configured. Set LLM_MODEL and LLM_BASE_URL.",
                status_code=503,
                code="llm_not_configured",
            )
        if self._settings.llm_api_key_required and not self._settings.llm_api_key:
            raise AppError(
                "LLM_API_KEY is not set. Add it to the backend environment. "
                "For a local OpenAI-compatible server, point LLM_BASE_URL at that server "
                "instead of https://api.openai.com/v1.",
                status_code=503,
                code="llm_not_configured",
            )

    def _parse(self, diff: str) -> ParsedDiff:
        try:
            return parse_unified_diff(diff)
        except DiffParseError as exc:
            raise AppError(str(exc), status_code=422, code="invalid_diff") from exc

    def _ensure_limits(self, diff: str, parsed: ParsedDiff, annotated: str) -> None:
        size = len(diff.encode("utf-8"))
        if size > self._settings.max_diff_bytes:
            raise AppError(
                f"The diff is {size} bytes, which exceeds the configured limit of "
                f"{self._settings.max_diff_bytes} bytes.",
                status_code=413,
                code="diff_too_large",
            )
        if len(parsed.files) > self._settings.max_diff_files:
            raise AppError(
                f"The diff touches {len(parsed.files)} files, which exceeds the configured limit of "
                f"{self._settings.max_diff_files}.",
                status_code=413,
                code="diff_too_large",
            )
        annotated_limit = max(self._settings.max_diff_bytes * 2, self._settings.max_diff_bytes + 20_000)
        if len(annotated.encode("utf-8")) > annotated_limit:
            raise AppError(
                "The annotated diff is too large to send for review. Narrow the change or raise MAX_DIFF_BYTES.",
                status_code=413,
                code="diff_too_large",
            )

    def _prior_limitations(self, parsed: ParsedDiff, source: GitHubReviewSource | None) -> list[str]:
        notes: list[str] = []
        binary = [item.path for item in parsed.files if item.is_binary]
        if binary:
            notes.append("Binary files were omitted from analysis: " + ", ".join(binary[:30]))
        if source:
            notes.extend(source.limitations)
            parsed_paths = {item.path for item in parsed.files}
            missing = [
                item.path
                for item in source.files
                if item.omitted and item.path not in parsed_paths and (item.previous_path or "") not in parsed_paths
            ]
            if missing:
                notes.append(
                    "These changed files had no text patch in the retrieved diff: "
                    + ", ".join(missing[:30])
                    + ". They may be binary or larger than GitHub's patch limit, so they were not reviewed."
                )
        return notes

    def _metadata(
        self,
        parsed: ParsedDiff,
        source: GitHubReviewSource | None,
        limitations: list[str],
    ) -> dict:
        if source and source.files:
            files = [
                {
                    "path": item.path,
                    "status": item.status,
                    "additions": item.additions,
                    "deletions": item.deletions,
                    "binary": False,
                    "omitted": item.omitted,
                }
                for item in source.files
            ]
        else:
            files = [
                {
                    "path": item.path,
                    "status": item.status,
                    "additions": item.additions,
                    "deletions": item.deletions,
                    "binary": item.is_binary,
                    "omitted": False,
                }
                for item in parsed.files
            ]
        metadata: dict = {
            "prompt_version": PROMPT_VERSION,
            "files": files,
            "pull_request": None,
            "omitted_files": [item["path"] for item in files if item["binary"] or item["omitted"]],
            "prior_limitations": limitations,
        }
        if source:
            metadata["pull_request"] = {
                "owner": source.owner,
                "repo": source.repo,
                "number": source.number,
                "url": source.url,
                "title": source.title,
                "head_sha": source.head_sha,
                "base_ref": source.base_ref,
                "author": source.author,
            }
        return metadata

    def _to_records(
        self,
        review_id: str,
        findings: list[ModelFinding],
        parsed: ParsedDiff,
    ) -> list[FindingRecord]:
        index = new_line_index(parsed)
        known_paths = set(index)
        records: list[FindingRecord] = []
        for position, finding in enumerate(findings):
            file_path = finding.file_path
            line_start = finding.line_start
            line_end = finding.line_end
            insufficient = finding.insufficient_context
            if file_path and file_path not in known_paths:
                matches = [path for path in known_paths if path.endswith("/" + file_path)]
                if len(matches) == 1:
                    file_path = matches[0]
                else:
                    insufficient = True
                    line_start = None
                    line_end = None
            if file_path in index and line_start is not None and line_start not in index[file_path]:
                line_start = None
                line_end = None
                insufficient = True
            records.append(
                FindingRecord(
                    id=str(uuid.uuid4()),
                    review_id=review_id,
                    title=finding.title,
                    explanation=finding.explanation,
                    severity=finding.severity,
                    category=finding.category,
                    kind=finding.kind,
                    file_path=file_path,
                    line_start=line_start,
                    line_end=line_end,
                    code_snippet=finding.code_snippet,
                    recommended_fix=finding.recommended_fix,
                    confidence=round(float(finding.confidence), 4),
                    suggested_patch=finding.suggested_patch,
                    insufficient_context=insufficient,
                    position=position,
                )
            )
        return records


def _diff_title(title: str | None, parsed: ParsedDiff) -> str:
    if title:
        return title[:200]
    paths = [item.path for item in parsed.files if item.path and item.path != "unknown"]
    if not paths:
        return "Untitled diff review"
    if len(paths) == 1:
        return f"Diff review: {paths[0]}"[:200]
    return f"Diff review: {paths[0]} and {len(paths) - 1} more"[:200]


def _merge_limitations(prior: list[str], model_note: str | None) -> str | None:
    parts = [item.strip() for item in prior if item and item.strip()]
    if model_note and model_note.strip():
        parts.append(model_note.strip())
    if not parts:
        return None
    return "\n".join(parts)


def _add(left: int | None, right: int | None) -> int | None:
    if left is None and right is None:
        return None
    return (left or 0) + (right or 0)
