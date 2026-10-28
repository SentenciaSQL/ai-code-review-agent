from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class LLMCompletion:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None


class LLMProvider(Protocol):
    """Replaceable completion provider. Business logic depends on this interface only."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def complete(self, *, system_prompt: str, user_prompt: str) -> LLMCompletion: ...
