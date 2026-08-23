from typing import Any

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.investigation import (
    FixtureProvider,
    InvestigationFailureKind,
    InvestigationMode,
    InvestigationService,
    ProviderError,
)
from ai_ran_assurance.investigation.models import (
    InvestigationContext,
    ProviderCallResult,
    ProviderMetadata,
    VerificationStatus,
)
from ai_ran_assurance.workflow import ClosedLoopEngine


def _core(run: Any) -> dict[str, Any]:
    return {
        "anomalies": run.anomalies,
        "diagnoses": run.diagnoses,
        "recommendations": run.recommendations,
        "decisions": run.decisions,
    }


class FailingProvider:
    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(provider="fixture", model="failure", live_model=False)

    def generate(
        self,
        context: InvestigationContext,
        *,
        system_instruction: str,
        rendered_context: str,
    ) -> ProviderCallResult:
        del context, system_instruction, rendered_context
        raise ProviderError("simulated provider outage")


def test_advisory_investigation_cannot_change_core_outputs(
    project_config: ProjectConfig,
) -> None:
    engine = ClosedLoopEngine(project_config, training_seed=17)
    without_ai = engine.run("congestion", seed=211)
    with_ai = engine.run("congestion", seed=211)
    before = _core(with_ai)
    report = InvestigationService(project_config, FixtureProvider()).investigate(
        topology=with_ai.topology,
        telemetry=with_ai.telemetry,
        anomalies=with_ai.anomalies,
    )
    assert report.verification.status is VerificationStatus.VERIFIED
    assert _core(without_ai) == before == _core(with_ai)
    assert report.can_modify_shadow_decision is False


def test_provider_failure_never_becomes_core_assurance_failure(
    project_config: ProjectConfig,
) -> None:
    run = ClosedLoopEngine(project_config, training_seed=17).run("outage", seed=101)
    expected = _core(run)
    report = InvestigationService(project_config, FailingProvider()).investigate(
        topology=run.topology,
        telemetry=run.telemetry,
        anomalies=run.anomalies,
    )
    assert report.investigation is None
    assert report.failure_kind is InvestigationFailureKind.PROVIDER
    assert report.verification.status is VerificationStatus.REJECTED
    assert _core(run) == expected


def test_review_mode_labels_deterministic_rca_as_candidate(
    project_config: ProjectConfig,
) -> None:
    run = ClosedLoopEngine(project_config, training_seed=17).run("bler", seed=101)
    report = InvestigationService(project_config, FixtureProvider()).investigate(
        topology=run.topology,
        telemetry=run.telemetry,
        anomalies=run.anomalies,
        mode=InvestigationMode.REVIEW,
        deterministic_diagnoses=run.diagnoses,
    )
    assert report.context.candidate_assessment is not None
    dumped = report.context.model_dump(mode="json")
    assert "ground_truth" not in str(dumped)
    assert "candidate_assessment" in dumped
