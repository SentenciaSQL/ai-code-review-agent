from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class DiffParseError(Exception):
    """The submitted text is not a usable unified diff."""


@dataclass(slots=True)
class ParsedLine:
    kind: str
    text: str
    new_line: int | None
    old_line: int | None


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[ParsedLine] = field(default_factory=list)


@dataclass(slots=True)
class ParsedFile:
    old_path: str
    new_path: str
    status: str
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    @property
    def path(self) -> str:
        if self.new_path and self.new_path != "/dev/null":
            return self.new_path
        if self.old_path and self.old_path != "/dev/null":
            return self.old_path
        return "unknown"


@dataclass(slots=True)
class ParsedDiff:
    files: list[ParsedFile]

    @property
    def additions(self) -> int:
        return sum(item.additions for item in self.files)

    @property
    def deletions(self) -> int:
        return sum(item.deletions for item in self.files)


def parse_unified_diff(text: str) -> ParsedDiff:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise DiffParseError("Diff content is empty.")

    lines = normalized.split("\n")
    if lines and lines[-1] == "" and normalized.endswith("\n"):
        lines = lines[:-1]

    files: list[ParsedFile] = []
    current: ParsedFile | None = None
    current_hunk: Hunk | None = None
    seen_old = 0
    seen_new = 0
    saw_git_header = False
    saw_hunk = False

    def ensure_file(old_path: str, new_path: str) -> ParsedFile:
        nonlocal current, current_hunk
        current = ParsedFile(
            old_path=old_path,
            new_path=new_path,
            status=_file_status(old_path, new_path),
        )
        files.append(current)
        current_hunk = None
        return current

    for raw_line in lines:
        if current_hunk is not None and seen_old >= current_hunk.old_count and seen_new >= current_hunk.new_count:
            current_hunk = None

        if raw_line.startswith("diff --git "):
            saw_git_header = True
            old_path, new_path = _split_git_paths(raw_line)
            ensure_file(old_path, new_path)
            continue

        if raw_line.startswith("Binary files ") or raw_line.startswith("GIT binary patch"):
            if current is None:
                ensure_file("unknown", "unknown")
            assert current is not None
            current.is_binary = True
            current_hunk = None
            continue

        if raw_line.startswith("rename from ") and current is not None and current_hunk is None:
            current.old_path = raw_line[len("rename from ") :].strip()
            current.status = _file_status(current.old_path, current.new_path)
            continue
        if raw_line.startswith("rename to ") and current is not None and current_hunk is None:
            current.new_path = raw_line[len("rename to ") :].strip()
            current.status = _file_status(current.old_path, current.new_path)
            continue

        if current_hunk is None and raw_line.startswith("--- "):
            path = _extract_header_path(raw_line[4:])
            if current is None:
                ensure_file(path, path)
            else:
                current.old_path = path
                current.status = _file_status(current.old_path, current.new_path)
            continue
        if current_hunk is None and raw_line.startswith("+++ "):
            path = _extract_header_path(raw_line[4:])
            if current is None:
                ensure_file(path, path)
            else:
                current.new_path = path
                current.status = _file_status(current.old_path, current.new_path)
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            saw_hunk = True
            if current is None:
                ensure_file("unknown", "unknown")
            assert current is not None
            current_hunk = Hunk(
                old_start=int(hunk_match.group(1)),
                old_count=int(hunk_match.group(2) or "1"),
                new_start=int(hunk_match.group(3)),
                new_count=int(hunk_match.group(4) or "1"),
            )
            current.hunks.append(current_hunk)
            seen_old = 0
            seen_new = 0
            continue

        if current_hunk is None or current is None:
            continue
        if raw_line.startswith("\\"):
            continue

        if raw_line.startswith("+"):
            current_hunk.lines.append(
                ParsedLine("add", raw_line[1:], current_hunk.new_start + seen_new, None)
            )
            current.additions += 1
            seen_new += 1
            continue
        if raw_line.startswith("-"):
            current_hunk.lines.append(
                ParsedLine("delete", raw_line[1:], None, current_hunk.old_start + seen_old)
            )
            current.deletions += 1
            seen_old += 1
            continue
        if raw_line.startswith(" "):
            current_hunk.lines.append(
                ParsedLine(
                    "context",
                    raw_line[1:],
                    current_hunk.new_start + seen_new,
                    current_hunk.old_start + seen_old,
                )
            )
            seen_old += 1
            seen_new += 1
            continue

    if not saw_git_header and not saw_hunk:
        raise DiffParseError(
            "This does not look like a unified Git diff. Paste output from git diff or git show, "
            "including the ---/+++ headers and @@ hunks."
        )
    if not files:
        raise DiffParseError("The diff does not contain any files.")

    reviewable = [item for item in files if not item.is_binary and item.hunks]
    if not reviewable:
        if any(item.is_binary for item in files):
            raise DiffParseError("The diff only contains binary files, which this review cannot analyze as text.")
        raise DiffParseError("The diff does not contain any reviewable changes.")
    return ParsedDiff(files=files)


def render_annotated_diff(parsed: ParsedDiff) -> str:
    blocks: list[str] = []
    for item in parsed.files:
        header = f"===== {item.path} ({item.status}) ====="
        if item.is_binary:
            blocks.append(f"{header}\nBinary file omitted. No text diff is available.")
            continue
        if not item.hunks:
            blocks.append(f"{header}\nNo textual hunks were included for this file.")
            continue
        parts = [header]
        for hunk in item.hunks:
            parts.append(
                f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@"
            )
            for line in hunk.lines:
                if line.kind == "add" and line.new_line is not None:
                    parts.append(f"{line.new_line:>5} | +{line.text}")
                elif line.kind == "delete":
                    parts.append(f"      | -{line.text}")
                elif line.new_line is not None:
                    parts.append(f"{line.new_line:>5} |  {line.text}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def new_line_index(parsed: ParsedDiff) -> dict[str, set[int]]:
    index: dict[str, set[int]] = {}
    for item in parsed.files:
        numbers: set[int] = set()
        for hunk in item.hunks:
            for line in hunk.lines:
                if line.new_line is not None:
                    numbers.add(line.new_line)
        index[item.path] = numbers
    return index


def _file_status(old_path: str, new_path: str) -> str:
    if old_path == "/dev/null":
        return "added"
    if new_path == "/dev/null":
        return "deleted"
    if (
        old_path
        and new_path
        and old_path != new_path
        and old_path not in {"unknown"}
        and new_path not in {"unknown"}
    ):
        return "renamed"
    return "modified"


def _extract_header_path(raw: str) -> str:
    value = raw.strip()
    if "\t" in value:
        value = value.split("\t", 1)[0].strip()
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    if value == "/dev/null":
        return "/dev/null"
    if value.startswith("a/") or value.startswith("b/"):
        return value[2:]
    return value


def _strip_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _split_git_paths(line: str) -> tuple[str, str]:
    rest = line[len("diff --git ") :].strip()
    if rest.startswith('"'):
        parts = _split_quoted(rest)
        if len(parts) >= 2:
            return _strip_prefix(parts[0]), _strip_prefix(parts[1])
    marker = " b/"
    index = rest.rfind(marker)
    if index == -1:
        return "unknown", "unknown"
    old = rest[:index]
    new = rest[index + len(marker) :]
    return _strip_prefix(old), new


def _split_quoted(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_quote = False
    escaped = False
    for char in value:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if char == " " and not in_quote:
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        parts.append("".join(current))
    return parts
