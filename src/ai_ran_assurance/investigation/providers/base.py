"""Provider dependency-inversion boundary."""

from __future__ import annotations

from typing import Protocol

from ai_ran_assurance.investigation.models import (
    InvestigationContext,
    ProviderCallResult,
    ProviderMetadata,
)


class ProviderError(RuntimeError):
    """A bounded provider failure that must not escape into core assurance."""


class ProviderUnavailableError(ProviderError):
    """Provider configuration or explicit live-call opt-in is absent."""


class InvestigationProvider(Protocol):
    @property
    def metadata(self) -> ProviderMetadata: ...

    def generate(
        self,
        context: InvestigationContext,
        *,
        system_instruction: str,
        rendered_context: str,
    ) -> ProviderCallResult: ...
