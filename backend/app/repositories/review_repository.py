from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models.review import (
    DashboardStats,
    FindingRecord,
    ReviewListItem,
    ReviewRecord,
    SeverityCounts,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class ReviewRepository:
    def __init__(self, database_path: str | Any) -> None:
        self.database_path = str(database_path)

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT,
                    status TEXT NOT NULL,
                    summary TEXT,
                    context_limitations TEXT,
                    provider TEXT,
                    model TEXT,
                    prompt_version TEXT,
                    error_message TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    file_path TEXT,
                    line_start INTEGER,
                    line_end INTEGER,
                    code_snippet TEXT,
                    recommended_fix TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    suggested_patch TEXT,
                    insufficient_context INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL,
                    FOREIGN KEY (review_id) REFERENCES reviews(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_reviews_created_at ON reviews (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_findings_review_id ON findings (review_id);
                """
            )

    def ping(self) -> None:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()

    def mark_interrupted(self) -> int:
        now = _iso(utcnow())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE reviews
                SET status = 'failed',
                    error_message = 'The review was interrupted before it finished.',
                    updated_at = ?,
                    completed_at = ?
                WHERE status = 'processing'
                """,
                (now, now),
            )
            return int(cursor.rowcount)

    def create(
        self,
        *,
        review_id: str,
        title: str,
        source_type: str,
        source_ref: str | None,
        provider: str,
        model: str,
        prompt_version: str,
        metadata: dict,
    ) -> ReviewRecord:
        now = utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reviews (
                    id, title, source_type, source_ref, status, summary, context_limitations,
                    provider, model, prompt_version, error_message, metadata_json,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, 'processing', NULL, NULL, ?, ?, ?, NULL, ?, ?, ?, NULL)
                """,
                (
                    review_id,
                    title,
                    source_type,
                    source_ref,
                    provider,
                    model,
                    prompt_version,
                    json.dumps(metadata, separators=(",", ":")),
                    _iso(now),
                    _iso(now),
                ),
            )
        stored = self.get(review_id)
        if stored is None:
            raise RuntimeError("The review record could not be read after it was created.")
        return stored

    def complete(
        self,
        review_id: str,
        *,
        summary: str,
        context_limitations: str | None,
        findings: list[FindingRecord],
        model: str,
        usage: dict[str, int | None],
    ) -> ReviewRecord:
        now = _iso(utcnow())
        with self._connect() as conn:
            row = conn.execute("SELECT metadata_json FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if row is None:
                raise KeyError(review_id)
            metadata = json.loads(row["metadata_json"] or "{}")
            metadata["usage"] = usage
            conn.execute("DELETE FROM findings WHERE review_id = ?", (review_id,))
            conn.execute(
                """
                UPDATE reviews
                SET status = 'completed',
                    summary = ?,
                    context_limitations = ?,
                    model = ?,
                    error_message = NULL,
                    metadata_json = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (
                    summary,
                    context_limitations,
                    model,
                    json.dumps(metadata, separators=(",", ":")),
                    now,
                    now,
                    review_id,
                ),
            )
            conn.executemany(
                """
                INSERT INTO findings (
                    id, review_id, title, explanation, severity, category, kind, file_path,
                    line_start, line_end, code_snippet, recommended_fix, confidence,
                    suggested_patch, insufficient_context, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        finding.id,
                        finding.review_id,
                        finding.title,
                        finding.explanation,
                        finding.severity,
                        finding.category,
                        finding.kind,
                        finding.file_path,
                        finding.line_start,
                        finding.line_end,
                        finding.code_snippet,
                        finding.recommended_fix,
                        finding.confidence,
                        finding.suggested_patch,
                        1 if finding.insufficient_context else 0,
                        finding.position,
                    )
                    for finding in findings
                ],
            )
        stored = self.get(review_id)
        if stored is None:
            raise RuntimeError("The completed review could not be read.")
        return stored

    def mark_failed(self, review_id: str, message: str) -> None:
        now = _iso(utcnow())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reviews
                SET status = 'failed',
                    error_message = ?,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ? AND status != 'completed'
                """,
                (message, now, now, review_id),
            )

    def get(self, review_id: str) -> ReviewRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
            if row is None:
                return None
            findings = conn.execute(
                "SELECT * FROM findings WHERE review_id = ? ORDER BY position ASC, id ASC",
                (review_id,),
            ).fetchall()
        return _review_from_row(row, [_finding_from_row(item) for item in findings])

    def list_reviews(self, *, limit: int, offset: int) -> tuple[list[ReviewListItem], int]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0])
            rows = conn.execute(
                """
                SELECT * FROM reviews
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            counts = _count_findings(conn, [row["id"] for row in rows])
        items = []
        for row in rows:
            review = _review_from_row(row, [])
            count = counts.get(review.id, _empty_count())
            items.append(
                ReviewListItem(
                    review=review,
                    finding_count=count["finding"],
                    suggestion_count=count["suggestion"],
                    severity_counts=count["severity"],
                )
            )
        return items, total

    def delete(self, review_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
            return cursor.rowcount > 0

    def stats(self) -> DashboardStats:
        with self._connect() as conn:
            total_reviews = int(conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0])
            completed = int(
                conn.execute("SELECT COUNT(*) FROM reviews WHERE status = 'completed'").fetchone()[0]
            )
            failed = int(conn.execute("SELECT COUNT(*) FROM reviews WHERE status = 'failed'").fetchone()[0])
            processing = int(
                conn.execute("SELECT COUNT(*) FROM reviews WHERE status = 'processing'").fetchone()[0]
            )
            severity = SeverityCounts()
            for row in conn.execute(
                """
                SELECT severity, COUNT(*) AS n
                FROM findings
                WHERE kind = 'finding'
                GROUP BY severity
                """
            ):
                _set_severity(severity, row["severity"], int(row["n"]))
            suggestions = int(
                conn.execute("SELECT COUNT(*) FROM findings WHERE kind = 'suggestion'").fetchone()[0]
            )
            categories: dict[str, int] = {}
            for row in conn.execute(
                """
                SELECT category, COUNT(*) AS n
                FROM findings
                WHERE kind = 'finding'
                GROUP BY category
                ORDER BY category
                """
            ):
                categories[str(row["category"])] = int(row["n"])
            total_findings = severity.critical + severity.high + severity.medium + severity.low
        return DashboardStats(
            total_reviews=total_reviews,
            completed_reviews=completed,
            failed_reviews=failed,
            processing_reviews=processing,
            total_findings=total_findings,
            total_suggestions=suggestions,
            findings_by_severity=severity,
            findings_by_category=categories,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return _CommitConnection(connection)


class _CommitConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self._connection

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()


def _review_from_row(row: sqlite3.Row, findings: list[FindingRecord]) -> ReviewRecord:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return ReviewRecord(
        id=row["id"],
        title=row["title"],
        source_type=row["source_type"],
        source_ref=row["source_ref"],
        status=row["status"],
        summary=row["summary"],
        context_limitations=row["context_limitations"],
        provider=row["provider"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        error_message=row["error_message"],
        metadata=metadata,
        created_at=_parse_dt(row["created_at"]) or utcnow(),
        updated_at=_parse_dt(row["updated_at"]) or utcnow(),
        completed_at=_parse_dt(row["completed_at"]),
        findings=findings,
    )


def _finding_from_row(row: sqlite3.Row) -> FindingRecord:
    return FindingRecord(
        id=row["id"],
        review_id=row["review_id"],
        title=row["title"],
        explanation=row["explanation"],
        severity=row["severity"],
        category=row["category"],
        kind=row["kind"],
        file_path=row["file_path"],
        line_start=row["line_start"],
        line_end=row["line_end"],
        code_snippet=row["code_snippet"],
        recommended_fix=row["recommended_fix"],
        confidence=float(row["confidence"]),
        suggested_patch=row["suggested_patch"],
        insufficient_context=bool(row["insufficient_context"]),
        position=int(row["position"]),
    )


def _empty_count() -> dict:
    return {"finding": 0, "suggestion": 0, "severity": SeverityCounts()}


def _count_findings(conn: sqlite3.Connection, review_ids: list[str]) -> dict[str, dict]:
    counts: dict[str, dict] = {review_id: _empty_count() for review_id in review_ids}
    if not review_ids:
        return counts
    placeholders = ",".join("?" for _ in review_ids)
    rows = conn.execute(
        f"""
        SELECT review_id, severity, kind, COUNT(*) AS n
        FROM findings
        WHERE review_id IN ({placeholders})
        GROUP BY review_id, severity, kind
        """,
        review_ids,
    ).fetchall()
    for row in rows:
        bucket = counts[row["review_id"]]
        amount = int(row["n"])
        if row["kind"] == "suggestion":
            bucket["suggestion"] += amount
            continue
        bucket["finding"] += amount
        severity = row["severity"]
        current = _severity_value(bucket["severity"], severity)
        _set_severity(bucket["severity"], severity, current + amount)
    return counts


def _severity_value(counts: SeverityCounts, severity: str) -> int:
    if severity == "critical":
        return counts.critical
    if severity == "high":
        return counts.high
    if severity == "medium":
        return counts.medium
    if severity == "low":
        return counts.low
    return 0


def _set_severity(counts: SeverityCounts, severity: str, value: int) -> None:
    if severity == "critical":
        counts.critical = value
    elif severity == "high":
        counts.high = value
    elif severity == "medium":
        counts.medium = value
    elif severity == "low":
        counts.low = value
