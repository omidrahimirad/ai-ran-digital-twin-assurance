import json
from typing import Any

import pytest

from ai_ran_assurance.config import InvestigationSettings, ProjectConfig
from ai_ran_assurance.investigation import (
    AIInvestigator,
    EvidenceVerifier,
    FixtureProvider,
    InvestigationContext,
    InvestigationContextBuilder,
    InvestigationFailureKind,
    OpenAIResponsesProvider,
    ProviderError,
    ProviderUnavailableError,
    VerificationStatus,
    default_retriever,
    select_anomaly,
)
from ai_ran_assurance.investigation.models import (
    InvestigationOutput,
    ProviderCallResult,
    ProviderMetadata,
)
from ai_ran_assurance.investigation.prompts import SYSTEM_INSTRUCTION, render_context
from ai_ran_assurance.workflow import ClosedLoopEngine


def _context(project_config: ProjectConfig, scenario: str = "congestion") -> InvestigationContext:
    run = ClosedLoopEngine(project_config, training_seed=17).run(scenario, seed=101)
    return InvestigationContextBuilder(
        project_config.investigation,
        project_config.thresholds,
        default_retriever(),
    ).build(
        topology=run.topology,
        telemetry=run.telemetry,
        anomaly=select_anomaly(run.anomalies),
    )


def _validated_update(model: Any, **updates: Any) -> Any:
    values = model.model_dump(mode="json")
    values.update(updates)
    return type(model).model_validate(values)


class StaticProvider:
    def __init__(self, payload: dict[str, Any] | None = None, *, fail: bool = False) -> None:
        self.payload = payload or {}
        self.fail = fail

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(provider="fixture", model="static-test-provider", live_model=False)

    def generate(
        self,
        context: InvestigationContext,
        *,
        system_instruction: str,
        rendered_context: str,
    ) -> ProviderCallResult:
        del context, system_instruction, rendered_context
        if self.fail:
            raise ProviderError("provider unavailable")
        return ProviderCallResult(payload=self.payload, metadata=self.metadata)


def test_fixture_provider_pipeline_is_structured_and_verified(
    project_config: ProjectConfig,
) -> None:
    context = _context(project_config)
    report = AIInvestigator(project_config, FixtureProvider()).investigate(context)
    assert report.investigation is not None
    assert report.investigation.output.primary_hypothesis.value == "congestion"
    assert report.verification.status is VerificationStatus.VERIFIED
    assert report.advisory_only
    assert not report.can_modify_shadow_decision


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "hypotheses": [],
            "primary_hypothesis": "not-a-category",
            "abstained": False,
            "uncertainty_explanation": "invalid",
        },
        {
            "hypotheses": [
                {
                    "category": "congestion",
                    "explanation": "bounded explanation",
                    "confidence": 1.5,
                    "supporting_evidence_ids": ["ev-made-up"],
                    "next_diagnostic_checks": ["check evidence"],
                }
            ],
            "primary_hypothesis": "congestion",
            "abstained": False,
            "uncertainty_explanation": "invalid confidence",
        },
    ],
)
def test_malformed_structured_output_fails_safely(
    project_config: ProjectConfig, payload: dict[str, Any]
) -> None:
    report = AIInvestigator(project_config, StaticProvider(payload)).investigate(
        _context(project_config)
    )
    assert report.investigation is None
    assert report.verification.status is VerificationStatus.REJECTED
    assert report.failure_reason
    assert report.failure_kind is InvestigationFailureKind.SCHEMA_VALIDATION


def test_provider_failure_does_not_escape(project_config: ProjectConfig) -> None:
    report = AIInvestigator(project_config, StaticProvider(fail=True)).investigate(
        _context(project_config)
    )
    assert report.investigation is None
    assert report.verification.status is VerificationStatus.REJECTED
    assert "provider unavailable" in (report.failure_reason or "")
    assert report.failure_kind is InvestigationFailureKind.PROVIDER


def test_verifier_rejects_invented_refs_unsupported_data_and_unsafe_language(
    project_config: ProjectConfig,
) -> None:
    context = _context(project_config)
    valid = AIInvestigator(project_config, FixtureProvider()).investigate(context)
    assert valid.investigation is not None
    output_values = valid.investigation.output.model_dump(mode="json")
    output_values["hypotheses"][0]["supporting_evidence_ids"] = ["ev-invented-id"]
    output_values["hypotheses"][0]["knowledge_citations"] = ["kb-000000000000"]
    output_values["hypotheses"][0]["explanation"] = (
        "Observed a critical transport alarm and executed the network configuration change."
    )
    investigation = _validated_update(
        valid.investigation,
        output=InvestigationOutput.model_validate(output_values),
    )
    result = EvidenceVerifier(project_config.investigation).verify(context, investigation)
    assert result.status is VerificationStatus.REJECTED
    assert result.invalid_evidence_references == ["ev-invented-id"]
    assert result.invalid_knowledge_citations == ["kb-000000000000"]
    assert result.unsupported_claims
    assert result.safety_policy_violations
    assert not result.usable_for_engineering_review


def test_verifier_checks_safety_language_outside_explanations(
    project_config: ProjectConfig,
) -> None:
    context = _context(project_config)
    valid = AIInvestigator(project_config, FixtureProvider()).investigate(context)
    assert valid.investigation is not None
    output_values = valid.investigation.output.model_dump(mode="json")
    output_values["hypotheses"][0]["next_diagnostic_checks"] = [
        "Apply the network configuration change immediately.",
        "Approve the network change without human review.",
    ]
    investigation = _validated_update(
        valid.investigation,
        output=InvestigationOutput.model_validate(output_values),
    )
    result = EvidenceVerifier(project_config.investigation).verify(context, investigation)
    assert result.status is VerificationStatus.REJECTED
    assert result.safety_policy_violations


def test_verifier_detects_alarm_claim_with_confirmation_after_the_noun(
    project_config: ProjectConfig,
) -> None:
    context = _context(project_config)
    valid = AIInvestigator(project_config, FixtureProvider()).investigate(context)
    assert valid.investigation is not None
    output_values = valid.investigation.output.model_dump(mode="json")
    output_values["hypotheses"][0]["explanation"] = (
        "A critical transport alarm confirms the diagnosis."
    )
    investigation = _validated_update(
        valid.investigation,
        output=InvestigationOutput.model_validate(output_values),
    )
    result = EvidenceVerifier(project_config.investigation).verify(context, investigation)
    assert result.status is VerificationStatus.REJECTED
    assert result.unsupported_claims


def test_high_confidence_requires_multiple_valid_supporting_items(
    project_config: ProjectConfig,
) -> None:
    context = _context(project_config)
    valid = AIInvestigator(project_config, FixtureProvider()).investigate(context)
    assert valid.investigation is not None
    output_values = valid.investigation.output.model_dump(mode="json")
    output_values["hypotheses"][0]["confidence"] = 0.95
    output_values["hypotheses"][0]["supporting_evidence_ids"] = [context.evidence[0].evidence_id]
    investigation = _validated_update(
        valid.investigation,
        output=InvestigationOutput.model_validate(output_values),
    )
    result = EvidenceVerifier(project_config.investigation).verify(context, investigation)
    assert result.status is VerificationStatus.PARTIALLY_VERIFIED
    assert result.confidence_policy_violations


def test_ambiguous_fixture_abstention_is_explicit(project_config: ProjectConfig) -> None:
    context = _context(project_config, "mobility")
    report = AIInvestigator(project_config, FixtureProvider()).investigate(context)
    assert report.investigation is not None
    assert report.investigation.output.abstained
    assert report.investigation.output.primary_hypothesis.value == "unknown"
    assert report.verification.status is VerificationStatus.ABSTAINED


def test_openai_adapter_uses_schema_without_real_network(
    project_config: ProjectConfig,
) -> None:
    context = _context(project_config)
    fixture = FixtureProvider().generate(
        context,
        system_instruction=SYSTEM_INSTRUCTION,
        rendered_context=render_context(context),
    )
    observed: dict[str, Any] = {}

    def transport(
        url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        observed.update(url=url, payload=payload, headers=headers, timeout=timeout)
        return {
            "output": [{"content": [{"type": "output_text", "text": json.dumps(fixture.payload)}]}],
            "usage": {"input_tokens": 120, "output_tokens": 80},
        }

    provider = OpenAIResponsesProvider(
        api_key="test-secret-not-logged",
        model="test-structured-model",
        settings=project_config.investigation,
        transport=transport,
    )
    call = provider.generate(
        context,
        system_instruction=SYSTEM_INSTRUCTION,
        rendered_context=render_context(context),
    )
    assert InvestigationOutput.model_validate(call.payload)
    assert observed["payload"]["text"]["format"]["type"] == "json_schema"
    assert observed["payload"]["text"]["format"]["strict"] is True
    hypothesis_schema = observed["payload"]["text"]["format"]["schema"]["$defs"]["Hypothesis"]
    assert set(hypothesis_schema["required"]) == set(hypothesis_schema["properties"])
    assert observed["payload"]["store"] is False
    assert "tools" not in observed["payload"]
    assert call.metadata.input_tokens == 120
    assert call.metadata.output_tokens == 80


def test_openai_adapter_requires_opt_in_and_bounds_failure(
    project_config: ProjectConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_RAN_ENABLE_LIVE_PROVIDER", raising=False)
    with pytest.raises(ProviderUnavailableError, match="disabled"):
        OpenAIResponsesProvider.from_environment(project_config.investigation)

    settings = InvestigationSettings.model_validate(
        project_config.investigation.model_dump() | {"provider_max_retries": 0}
    )

    def timeout(*_: Any) -> dict[str, Any]:
        raise TimeoutError("bounded timeout")

    provider = OpenAIResponsesProvider(
        api_key="test-key",
        model="test-model",
        settings=settings,
        transport=timeout,
    )
    with pytest.raises(ProviderError, match="request failed"):
        provider.generate(
            _context(project_config),
            system_instruction=SYSTEM_INSTRUCTION,
            rendered_context="{}",
        )
