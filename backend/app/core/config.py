from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


def resolve_env_file() -> Path:
    """Prefer the backend .env, then the repository root .env."""
    for candidate in (BACKEND_ROOT / ".env", REPO_ROOT / ".env"):
        if candidate.is_file():
            return candidate
    return REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Environment-backed settings. Secrets stay in the environment, never in code."""

    model_config = SettingsConfigDict(
        env_file=resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Patchline"
    app_version: str = "1.0.0"
    environment: str = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    llm_provider: str = "openai_compatible"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = Field(default=120, gt=0, le=600)
    llm_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_max_output_tokens: int = Field(default=8192, ge=256, le=32000)

    github_token: str = ""
    github_api_base_url: str = "https://api.github.com"
    github_web_host: str = "github.com"
    github_timeout_seconds: float = Field(default=30, gt=0, le=120)

    database_path: str = "data/reviews.db"
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"

    max_diff_bytes: int = Field(default=100_000, ge=1_000, le=2_000_000)
    max_diff_files: int = Field(default=80, ge=1, le=500)
    max_findings: int = Field(default=30, ge=1, le=100)
    max_request_bytes: int = Field(default=150_000, ge=1_000, le=3_000_000)

    @field_validator("llm_base_url", "github_api_base_url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("github_web_host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        cleaned = value.strip().lower()
        for prefix in ("https://", "http://"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
        return cleaned.strip("/")

    @field_validator("llm_provider", "llm_model", "llm_api_key", "github_token", "log_level", "app_name")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def check_limits(self) -> Settings:
        if self.max_request_bytes < self.max_diff_bytes + 1024:
            raise ValueError(
                "MAX_REQUEST_BYTES must be at least 1024 bytes larger than MAX_DIFF_BYTES "
                "so the JSON envelope fits around the diff."
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_database_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    @property
    def llm_api_key_required(self) -> bool:
        host = (urlparse(self.llm_base_url).hostname or "").lower()
        return host == "api.openai.com"

    @property
    def llm_configured(self) -> bool:
        if not self.llm_provider.strip() or not self.llm_model.strip() or not self.llm_base_url.strip():
            return False
        if self.llm_api_key_required and not self.llm_api_key.strip():
            return False
        return True

    @property
    def github_token_configured(self) -> bool:
        return bool(self.github_token.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
