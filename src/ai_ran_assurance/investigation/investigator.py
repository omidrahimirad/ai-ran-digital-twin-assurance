"""Advisory investigation orchestration and safe provider failure boundary."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pydantic import ValidationError

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.domain.models import (
    Anomaly,
    KPISample,
    NetworkTopology,
    RootCauseDiagnosis,
)
from ai_ran_assurance.investigation.context import (
    InvestigationContextBuilder,
    select_anomaly,
)
from ai_ran_assurance.investigation.models import (
    AIInvestigation,
    InvestigationContext,
    InvestigationFailureKind,
    InvestigationMode,
    InvestigationOutput,
    InvestigationReport,
)
from ai_ran_assurance.investigation.prompts import SYSTEM_INSTRUCTION, render_context
from ai_ran_assurance.investigation.providers import (
    FixtureProvider,
    InvestigationProvider,
    OpenAIResponsesProvider,
    ProviderError,
    ProviderUnavailableError,
)
from ai_ran_assurance.investigation.retrieval import LexicalRetriever
from ai_ran_assurance.investigation.verifier import EvidenceVerifier, rejected_verification

LOGGER = logging.getLogger(__name__)


def _failed_report(
    context: InvestigationContext,
    exc: Exception,
    kind: InvestigationFailureKind,
    provider: str,
) -> InvestigationReport:
    reason = f"{type(exc).__name__}: {exc}"[:500]
    LOGGER.warning(
        "ai_investigation_failed provider=%s cell=%s failure_kind=%s reason=%s",
        provider,
        context.analyzed_cell,
        kind.value,
        reason,
    )
    return InvestigationReport(
        context=context,
        investigation=None,
        verification=rejected_verification(reason),
        failure_reason=reason,
        failure_kind=kind,
    )


def default_knowledge_paths() -> list[Path]:
    root = Path(__file__).resolve().parent / "knowledge"
    return sorted(root.glob("*.md"))


def default_retriever() -> LexicalRetriever:
    paths = default_knowledge_paths()
    return LexicalRetriever.from_paths(paths, source_root=Path(__file__).resolve().parent)


def provider_from_name(name: str, config: ProjectConfig) -> InvestigationProvider:
    normalized = name.strip().lower()
    if normalized == "fixture":
        return FixtureProvider()
    if normalized == "openai":
        return OpenAIResponsesProvider.from_environment(config.investigation)
    raise ProviderUnavailableError(f"unknown investigation provider {name!r}")


def _investigation_id(
    context: InvestigationContext, output: InvestigationOutput, provider: str, model: str
) -> str:
    material = json.dumps(
        {
            "context": context.model_dump(mode="json"),
            "output": output.model_dump(mode="json"),
            "provider": provider,
            "model": model,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"inv-{hashlib.sha256(material).hexdigest()[:16]}"


class AIInvestigator:
    def __init__(self, config: ProjectConfig, provider: InvestigationProvider) -> None:
        self.config = config
        self.provider = provider
        self.verifier = EvidenceVerifier(config.investigation)

    def investigate(self, context: InvestigationContext) -> InvestigationReport:
        try:
            call = self.provider.generate(
                context,
                system_instruction=SYSTEM_INSTRUCTION,
                rendered_context=render_context(context),
            )
            output = InvestigationOutput.model_validate(call.payload)
            if len(output.hypotheses) > self.config.investigation.max_hypotheses:
                raise ValueError("provider returned more hypotheses than the configured maximum")
            investigation = AIInvestigation(
                investigation_id=_investigation_id(
                    context, output, call.metadata.provider, call.metadata.model
                ),
                analyzed_cell=context.analyzed_cell,
                analyzed_timestamp=context.analyzed_timestamp,
                output=output,
                provider=call.metadata,
                prompt_version=context.metadata.prompt_version,
            )
            verification = self.verifier.verify(context, investigation)
            LOGGER.info(
                "ai_investigation_completed provider=%s live_model=%s cell=%s status=%s",
                call.metadata.provider,
                call.metadata.live_model,
                context.analyzed_cell,
                verification.status.value,
            )
            return InvestigationReport(
                context=context,
                investigation=investigation,
                verification=verification,
            )
        except ProviderError as exc:
            return _failed_report(
                context,
                exc,
                InvestigationFailureKind.PROVIDER,
                self.provider.metadata.provider,
            )
        except ValidationError as exc:
            return _failed_report(
                context,
                exc,
                InvestigationFailureKind.SCHEMA_VALIDATION,
                self.provider.metadata.provider,
            )
        except ValueError as exc:
            return _failed_report(
                context,
                exc,
                InvestigationFailureKind.POLICY_VALIDATION,
                self.provider.metadata.provider,
            )


class InvestigationService:
    """Build context from explicit observable arguments and run the advisory provider."""

    def __init__(
        self,
        config: ProjectConfig,
        provider: InvestigationProvider,
        *,
        retriever: LexicalRetriever | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.context_builder = InvestigationContextBuilder(
            config.investigation,
            config.thresholds,
            retriever or default_retriever(),
        )
        self.investigator = AIInvestigator(config, provider)

    def investigate(
        self,
        *,
        topology: NetworkTopology,
        telemetry: list[KPISample],
        anomalies: list[Anomaly],
        cell_id: str | None = None,
        mode: InvestigationMode = InvestigationMode.INDEPENDENT,
        deterministic_diagnoses: list[RootCauseDiagnosis] | None = None,
    ) -> InvestigationReport:
        candidate: RootCauseDiagnosis | None = None
        if mode is InvestigationMode.REVIEW:
            candidates = [
                item
                for item in deterministic_diagnoses or []
                if cell_id is None or item.cell_id == cell_id
            ]
            if not candidates:
                raise ValueError("review mode has no matching deterministic RCA candidate")
            candidate = sorted(candidates, key=lambda item: (item.timestamp, item.cell_id))[0]
            matches = [
                item
                for item in anomalies
                if item.cell_id == candidate.cell_id and item.timestamp == candidate.timestamp
            ]
            if not matches:
                raise ValueError("review candidate has no matching observable anomaly")
            anomaly = matches[0]
        else:
            anomaly = select_anomaly(anomalies, cell_id)
        context = self.context_builder.build(
            topology=topology,
            telemetry=telemetry,
            anomaly=anomaly,
            mode=mode,
            deterministic_candidate=candidate,
        )
        return self.investigator.investigate(context)
