from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

import httpx

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.redaction import redact

logger = logging.getLogger(__name__)

_OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(slots=True)
class GitHubFile:
    path: str
    status: str
    additions: int
    deletions: int
    previous_path: str | None = None
    omitted: bool = False
    patch: str | None = None


@dataclass(slots=True)
class GitHubReviewSource:
    owner: str
    repo: str
    number: int
    title: str
    url: str
    head_sha: str | None
    base_ref: str | None
    author: str | None
    diff: str
    files: list[GitHubFile] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


class GitHubService:
    """Read pull request metadata and diffs. The token never leaves this service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch_pull_request(self, repository_url: str, pull_request_number: int | None) -> GitHubReviewSource:
        owner, repo, number = parse_github_reference(
            repository_url,
            pull_request_number,
            web_host=self._settings.github_web_host,
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Patchline",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = self._settings.github_token.strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        owner_q = quote(owner, safe="")
        repo_q = quote(repo, safe="")
        pr_url = (
            f"{self._settings.github_api_base_url}/repos/{owner_q}/{repo_q}/pulls/{number}"
        )
        timeout = httpx.Timeout(self._settings.github_timeout_seconds)

        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            metadata_response = self._send(client, pr_url, headers)
            metadata = self._json_object(metadata_response)
            diff_headers = dict(headers)
            diff_headers["Accept"] = "application/vnd.github.diff"
            diff_text, diff_error = self._read_diff(client, pr_url, diff_headers)
            files, file_error = self._read_files(
                client,
                f"{pr_url}/files",
                headers,
                keep_patches=not bool(diff_text),
            )

        if not diff_text:
            diff_text = _diff_from_file_patches(files)
        if not diff_text.strip():
            detail = diff_error or file_error or "GitHub did not return a text diff for this pull request."
            raise AppError(detail, status_code=422, code="github_empty_diff")

        limitations: list[str] = []
        if diff_error and _diff_from_file_patches(files):
            limitations.append(
                "The combined pull request diff was unavailable, so the review used per-file patches. "
                + diff_error
            )
        if file_error:
            limitations.append(file_error)

        title = _string(metadata.get("title")) or f"{owner}/{repo}#{number}"
        url = _string(metadata.get("html_url")) or (
            f"https://{self._settings.github_web_host}/{owner}/{repo}/pull/{number}"
        )
        head = metadata.get("head") if isinstance(metadata.get("head"), dict) else {}
        base = metadata.get("base") if isinstance(metadata.get("base"), dict) else {}
        user = metadata.get("user") if isinstance(metadata.get("user"), dict) else {}
        author = _string(user.get("login")) if isinstance(user, dict) else None

        logger.info("Fetched GitHub pull request %s/%s#%s", owner, repo, number)
        return GitHubReviewSource(
            owner=owner,
            repo=repo,
            number=number,
            title=title[:200],
            url=url,
            head_sha=_string(head.get("sha")) if isinstance(head, dict) else None,
            base_ref=_string(base.get("ref")) if isinstance(base, dict) else None,
            author=author,
            diff=diff_text,
            files=files,
            limitations=limitations,
        )

    def _send(self, client: httpx.Client, url: str, headers: dict[str, str]) -> httpx.Response:
        try:
            response = client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise AppError(
                "The GitHub request timed out. Try again, or raise GITHUB_TIMEOUT_SECONDS.",
                status_code=504,
                code="github_timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "The GitHub API could not be reached. Check GITHUB_API_BASE_URL and the network.",
                status_code=502,
                code="github_unreachable",
            ) from exc
        self._raise_for_status(response)
        return response

    def _read_diff(
        self,
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
    ) -> tuple[str, str | None]:
        try:
            with client.stream("GET", url, headers=headers) as response:
                if response.is_redirect or response.status_code >= 400:
                    response.read()
                    self._raise_for_status(response)
                return self._read_capped(response), None
        except AppError as exc:
            if exc.code == "diff_too_large":
                raise
            logger.info("GitHub diff request failed code=%s", exc.code)
            return "", exc.message

    def _read_files(
        self,
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
        *,
        keep_patches: bool,
    ) -> tuple[list[GitHubFile], str | None]:
        files: list[GitHubFile] = []
        page = 1
        try:
            while page <= 10:
                try:
                    response = client.get(
                        url,
                        headers=headers,
                        params={"per_page": 100, "page": page},
                    )
                except httpx.TimeoutException as exc:
                    raise AppError(
                        "The GitHub file list request timed out.",
                        status_code=504,
                        code="github_timeout",
                    ) from exc
                except httpx.HTTPError as exc:
                    raise AppError(
                        "The GitHub file list could not be retrieved.",
                        status_code=502,
                        code="github_unreachable",
                    ) from exc
                self._raise_for_status(response)
                payload = response.json()
                if not isinstance(payload, list) or not payload:
                    break
                for item in payload:
                    if isinstance(item, dict):
                        files.append(_file_from_api(item, keep_patch=keep_patches))
                patch_bytes = sum(len(item.patch.encode("utf-8")) for item in files if item.patch)
                if keep_patches and patch_bytes > self._settings.max_diff_bytes:
                    raise AppError(
                        "The pull request patches exceed the configured limit of "
                        f"{self._settings.max_diff_bytes} bytes.",
                        status_code=413,
                        code="diff_too_large",
                    )
                if len(payload) < 100:
                    break
                page += 1
            else:
                return files, "The pull request file list was truncated after 1000 files."
        except AppError as exc:
            if exc.code == "diff_too_large":
                raise
            logger.info("GitHub files request failed code=%s", exc.code)
            return files, exc.message
        return files, None

    def _read_capped(self, response: httpx.Response) -> str:
        chunks: list[bytes] = []
        total = 0
        limit = self._settings.max_diff_bytes
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > limit:
                raise AppError(
                    "The pull request diff exceeds the configured limit of "
                    f"{limit} bytes. Review a smaller change or raise MAX_DIFF_BYTES.",
                    status_code=413,
                    code="diff_too_large",
                )
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_redirect:
            raise AppError(
                "GitHub returned a redirect. Patchline does not follow it, so credentials stay on the API host.",
                status_code=502,
                code="github_redirect",
            )
        if response.status_code < 400:
            return

        remaining = response.headers.get("x-ratelimit-remaining")
        message = _github_message(response)
        if response.status_code == 429 or (response.status_code == 403 and remaining == "0"):
            raise AppError(
                "GitHub rate limit reached. Add GITHUB_TOKEN on the backend for a higher limit, or try again later.",
                status_code=429,
                code="github_rate_limit",
            )
        if response.status_code == 401:
            raise AppError(
                "GitHub rejected the configured token. Check GITHUB_TOKEN.",
                status_code=401,
                code="github_unauthorized",
            )
        if response.status_code == 403:
            raise AppError(
                message
                or "GitHub refused access to this repository. It may be private, or the token may lack pull request access.",
                status_code=403,
                code="github_forbidden",
            )
        if response.status_code == 404:
            hint = (
                ""
                if self._settings.github_token_configured
                else " If the repository is private, set GITHUB_TOKEN on the backend."
            )
            raise AppError(
                f"Pull request not found, or it is not accessible.{hint}",
                status_code=404,
                code="github_not_found",
            )
        if response.status_code == 422:
            raise AppError(
                message or "GitHub could not process this pull request reference.",
                status_code=422,
                code="github_invalid",
            )
        raise AppError(
            message or f"GitHub request failed with status {response.status_code}.",
            status_code=502,
            code="github_error",
        )

    @staticmethod
    def _json_object(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                "GitHub returned a response that was not JSON.",
                status_code=502,
                code="github_invalid_response",
            ) from exc
        if not isinstance(payload, dict):
            raise AppError(
                "GitHub returned an unexpected pull request payload.",
                status_code=502,
                code="github_invalid_response",
            )
        return payload


def parse_github_reference(
    repository_url: str,
    pull_request_number: int | None,
    *,
    web_host: str,
) -> tuple[str, str, int]:
    raw = repository_url.strip()
    if not raw:
        raise AppError(
            "Enter a GitHub repository or pull request URL.",
            status_code=422,
            code="invalid_github_reference",
        )
    lowered = raw.lower()
    if lowered.startswith(("file:", "git@", "ssh:", "http://127.", "http://localhost", "https://localhost")):
        raise AppError(
            f"Use an https://{web_host} repository or pull request URL.",
            status_code=422,
            code="invalid_github_reference",
        )

    owner: str | None = None
    repo: str | None = None
    url_number: int | None = None

    if "://" in raw or raw.lower().startswith(web_host) or raw.lower().startswith("www."):
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        if parsed.scheme not in {"http", "https"}:
            raise AppError(
                f"Use an https://{web_host} repository or pull request URL.",
                status_code=422,
                code="invalid_github_reference",
            )
        if parsed.username or parsed.password:
            raise AppError(
                "Remove credentials from the GitHub URL. Set GITHUB_TOKEN on the backend instead.",
                status_code=422,
                code="invalid_github_reference",
            )
        host = (parsed.hostname or "").lower()
        allowed = {web_host.lower(), f"www.{web_host.lower()}"}
        if host not in allowed:
            raise AppError(
                f"Only {web_host} repositories are accepted. Other hosts are rejected so this server cannot be pointed at arbitrary addresses.",
                status_code=422,
                code="invalid_github_host",
            )
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) < 2:
            raise AppError(
                "The URL must include an owner and a repository.",
                status_code=422,
                code="invalid_github_reference",
            )
        owner = parts[0]
        repo = parts[1].removesuffix(".git")
        if len(parts) >= 4 and parts[2] == "pull":
            number_text = parts[3].split(".", 1)[0]
            if not number_text.isdigit():
                raise AppError(
                    "The pull request URL does not include a numeric pull request.",
                    status_code=422,
                    code="invalid_github_reference",
                )
            url_number = int(number_text)
        elif len(parts) > 2 and parts[2] != "pull":
            raise AppError(
                "Use a repository URL or a pull request URL ending in /pull/<number>.",
                status_code=422,
                code="invalid_github_reference",
            )
    else:
        short = raw.removesuffix(".git")
        pieces = short.split("/")
        if len(pieces) != 2:
            raise AppError(
                "Enter a repository as owner/repo, or paste a full pull request URL.",
                status_code=422,
                code="invalid_github_reference",
            )
        owner, repo = pieces

    if owner is None or repo is None or not _OWNER_RE.fullmatch(owner) or not _OWNER_RE.fullmatch(repo):
        raise AppError(
            "The repository owner or name contains unsupported characters.",
            status_code=422,
            code="invalid_github_reference",
        )
    if url_number is not None and pull_request_number is not None and url_number != pull_request_number:
        raise AppError(
            "The pull request number does not match the number in the URL.",
            status_code=422,
            code="pull_request_mismatch",
        )
    resolved = url_number if url_number is not None else pull_request_number
    if resolved is None:
        raise AppError(
            "Enter a pull request number, or paste the full pull request URL.",
            status_code=422,
            code="pull_request_required",
        )
    return owner, repo, resolved


def _file_from_api(item: dict, *, keep_patch: bool) -> GitHubFile:
    status = _string(item.get("status")) or "modified"
    if status == "removed":
        status = "deleted"
    path = _string(item.get("filename")) or "unknown"
    patch = item.get("patch") if isinstance(item.get("patch"), str) else None
    changes = int(item.get("changes") or 0)
    return GitHubFile(
        path=path,
        status=status,
        additions=int(item.get("additions") or 0),
        deletions=int(item.get("deletions") or 0),
        previous_path=_string(item.get("previous_filename")),
        omitted=patch is None and changes > 0,
        patch=patch if keep_patch else None,
    )


def _diff_from_file_patches(files: list[GitHubFile]) -> str:
    parts: list[str] = []
    for item in files:
        if not item.patch or not item.patch.strip():
            continue
        previous = item.previous_path or item.path
        old_header = "/dev/null" if item.status == "added" else previous
        new_header = "/dev/null" if item.status == "deleted" else item.path
        old_prefix = "/dev/null" if old_header == "/dev/null" else f"a/{old_header}"
        new_prefix = "/dev/null" if new_header == "/dev/null" else f"b/{new_header}"
        parts.append(
            "\n".join(
                [
                    f"diff --git a/{previous} b/{item.path}",
                    f"--- {old_prefix}",
                    f"+++ {new_prefix}",
                    item.patch,
                ]
            )
        )
    return "\n".join(parts)


def _github_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return redact(payload["message"], limit=300)
    return ""


def _string(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None
