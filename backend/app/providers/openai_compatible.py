from __future__ import annotations

import logging

import httpx

from app.core.config import Settings
from app.core.exceptions import AppError, LLMProviderError
from app.core.redaction import redact
from app.providers.base import LLMCompletion

logger = logging.getLogger(__name__)


class _CompatibilityRejection(Exception):
    def __init__(self, body: str) -> None:
        super().__init__(body)
        self.body = body


class OpenAICompatibleProvider:
    """Calls an OpenAI-compatible POST /chat/completions endpoint."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._settings.llm_model

    def complete(self, *, system_prompt: str, user_prompt: str) -> LLMCompletion:
        try:
            return self._request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=True,
                token_field="max_tokens",
                temperature=self._settings.llm_temperature,
            )
        except _CompatibilityRejection as exc:
            body = exc.body.lower()
            response_format = "response_format" not in body
            token_field = "max_tokens"
            temperature: float | None = self._settings.llm_temperature
            adjusted = False
            if "response_format" in body:
                response_format = False
                adjusted = True
            if "max_completion_tokens" in body and "max_tokens" in body:
                token_field = "max_completion_tokens"
                adjusted = True
            elif "max_tokens" in body and "unsupported" in body:
                token_field = "max_completion_tokens"
                adjusted = True
            if "temperature" in body and any(word in body for word in ("unsupported", "not supported")):
                temperature = None
                adjusted = True
            if not adjusted:
                raise LLMProviderError(redact(exc.body)) from exc
            logger.info("Retrying LLM request once with compatible parameters")
            try:
                return self._request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format=response_format,
                    token_field=token_field,
                    temperature=temperature,
                )
            except _CompatibilityRejection as second:
                raise LLMProviderError(redact(second.body)) from second

    def _request(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: bool,
        token_field: str,
        temperature: float | None,
    ) -> LLMCompletion:
        url = self._chat_url()
        payload: dict = {
            "model": self._settings.llm_model,
            token_field: self._settings.llm_max_output_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if response_format:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json", "User-Agent": "Patchline"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"

        timeout = httpx.Timeout(self._settings.llm_timeout_seconds)
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                response = client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                "The language model request timed out. Increase LLM_TIMEOUT_SECONDS or review a smaller diff."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(
                "The language model provider could not be reached. Check LLM_BASE_URL and the network."
            ) from exc

        if response.is_redirect:
            raise LLMProviderError(
                "The language model provider returned a redirect. Check LLM_BASE_URL."
            )
        if response.status_code == 400:
            message = _error_message(response)
            raise _CompatibilityRejection(message)
        if response.status_code in {401, 403}:
            raise LLMProviderError(
                "The language model provider rejected the API key. Check LLM_API_KEY and LLM_BASE_URL."
            )
        if response.status_code == 429:
            raise LLMProviderError("The language model provider rate-limited the request. Try again later.")
        if response.status_code >= 400:
            raise LLMProviderError(
                _error_message(response)
                or f"The language model provider returned status {response.status_code}."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMProviderError("The language model provider returned a response that was not JSON.") from exc
        if not isinstance(body, dict):
            raise LLMProviderError("The language model provider returned an unexpected payload.")

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMProviderError("The language model provider returned no choices.")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("The language model returned an empty response.")

        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        model = body.get("model") if isinstance(body.get("model"), str) and body.get("model") else self._settings.llm_model
        finish_reason = choices[0].get("finish_reason")
        logger.info(
            "LLM request completed status=%s finish_reason=%s",
            response.status_code,
            finish_reason if isinstance(finish_reason, str) else "unknown",
        )
        return LLMCompletion(
            content=content,
            model=model,
            prompt_tokens=_optional_int(usage.get("prompt_tokens")),
            completion_tokens=_optional_int(usage.get("completion_tokens")),
            finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        )

    def _chat_url(self) -> str:
        base = self._settings.llm_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def build_provider(settings: Settings) -> OpenAICompatibleProvider:
    if settings.llm_provider != "openai_compatible":
        raise AppError(
            f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. Use openai_compatible.",
            status_code=503,
            code="llm_not_configured",
        )
    return OpenAICompatibleProvider(settings)


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return redact(response.text or "", limit=300)
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return redact(error["message"])
        if isinstance(error, str):
            return redact(error)
        if isinstance(payload.get("message"), str):
            return redact(payload["message"])
    return f"The language model provider returned status {response.status_code}."


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None
