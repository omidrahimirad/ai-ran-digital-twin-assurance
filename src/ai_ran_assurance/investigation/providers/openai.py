"""Explicitly opted-in OpenAI Responses API adapter using schema-constrained output."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from ai_ran_assurance.config import InvestigationSettings
from ai_ran_assurance.investigation.models import (
    InvestigationContext,
    InvestigationOutput,
    ProviderCallResult,
    ProviderMetadata,
)
from ai_ran_assurance.investigation.providers.base import (
    ProviderError,
    ProviderUnavailableError,
)

Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _urlopen_transport(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    # The provider endpoint is a fixed HTTPS URL; the transport remains injectable for tests.
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
        decoded = json.loads(response.read().decode())
    if not isinstance(decoded, dict):
        raise ProviderError("provider returned a non-object response")
    return decoded


def _output_text(response: dict[str, Any]) -> str:
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    return text
    raise ProviderError("provider response did not contain structured output text")


class OpenAIResponsesProvider:
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        settings: InvestigationSettings,
        transport: Transport = _urlopen_transport,
    ) -> None:
        if not api_key:
            raise ProviderUnavailableError("OPENAI_API_KEY is required")
        if not model:
            raise ProviderUnavailableError("AI_RAN_OPENAI_MODEL is required")
        self._api_key = api_key
        self._model = model
        self._settings = settings
        self._transport = transport

    @classmethod
    def from_environment(cls, settings: InvestigationSettings) -> OpenAIResponsesProvider:
        if os.getenv("AI_RAN_ENABLE_LIVE_PROVIDER") != "1":
            raise ProviderUnavailableError(
                "live provider disabled; set AI_RAN_ENABLE_LIVE_PROVIDER=1 explicitly"
            )
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("AI_RAN_OPENAI_MODEL", ""),
            settings=settings,
        )

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider="openai",
            model=self._model,
            live_model=True,
            temperature=0,
        )

    def generate(
        self,
        context: InvestigationContext,
        *,
        system_instruction: str,
        rendered_context: str,
    ) -> ProviderCallResult:
        del context
        schema = InvestigationOutput.model_json_schema()
        payload: dict[str, Any] = {
            "model": self._model,
            "instructions": system_instruction,
            "input": rendered_context,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ran_investigation",
                    "strict": True,
                    "schema": schema,
                }
            },
            "temperature": 0,
            "max_output_tokens": self._settings.max_output_tokens,
            "store": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self._settings.provider_max_retries + 1):
            try:
                response = self._transport(
                    self.endpoint,
                    payload,
                    headers,
                    self._settings.provider_timeout_seconds,
                )
                break
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ProviderError) as exc:
                last_error = exc
            if attempt < self._settings.provider_max_retries:
                time.sleep(0.1 * (attempt + 1))
        if response is None:
            detail = type(last_error).__name__ if last_error is not None else "unknown error"
            raise ProviderError(f"OpenAI provider request failed: {detail}") from last_error
        try:
            structured = json.loads(_output_text(response))
        except json.JSONDecodeError as exc:
            raise ProviderError("provider structured output was not valid JSON") from exc
        if not isinstance(structured, dict):
            raise ProviderError("provider structured output was not a JSON object")
        raw_usage = response.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        metadata = ProviderMetadata(
            provider="openai",
            model=self._model,
            live_model=True,
            latency_ms=round((time.perf_counter() - started) * 1000, 3),
            input_tokens=input_tokens if isinstance(input_tokens, int) else None,
            output_tokens=output_tokens if isinstance(output_tokens, int) else None,
            temperature=0,
        )
        return ProviderCallResult(payload=structured, metadata=metadata)
