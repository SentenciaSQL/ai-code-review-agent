from __future__ import annotations


class AppError(Exception):
    """Expected failure that maps to an HTTP response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str,
        review_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.review_id = review_id


class LLMProviderError(Exception):
    """The language model provider failed or could not be reached."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMResponseError(Exception):
    """The provider responded, but the payload was not a valid review."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
