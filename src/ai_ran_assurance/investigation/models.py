"""Strict contracts for the advisory AI investigation layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ai_ran_assurance.domain.enums import AnomalyType, RootCauseCategory


class InvestigationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class InvestigationMode(StrEnum):
    INDEPENDENT = "independent"
    REVIEW = "review"


class EvidenceKind(StrEnum):
    ANOMALY = "anomaly"
    TELEMETRY = "telemetry"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    REJECTED = "rejected"
    ABSTAINED = "abstained"


class InvestigationFailureKind(StrEnum):
    PROVIDER = "provider"
    SCHEMA_VALIDATION = "schema_validation"
    POLICY_VALIDATION = "policy_validation"


class KPIValue(InvestigationModel):
    value: float
    unit: str = Field(min_length=1, max_length=16)


class EvidenceItem(InvestigationModel):
    evidence_id: str = Field(pattern=r"^ev-[a-z0-9-]{3,96}$")
    timestamp: AwareDatetime
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    kind: EvidenceKind
    source: str = Field(min_length=1, max_length=80)
    facts: dict[str, KPIValue] = Field(min_length=1, max_length=10)
    description: str = Field(min_length=1, max_length=300)


class RetrievedKnowledge(InvestigationModel):
    chunk_id: str = Field(pattern=r"^kb-[a-f0-9]{12}$")
    source_path: str = Field(min_length=1, max_length=240)
    heading: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=2400)
    relevance_score: float = Field(ge=0, le=1)


class ObservableAnomaly(InvestigationModel):
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    timestamp: AwareDatetime
    anomaly_type: AnomalyType
    score: float = Field(ge=0)
    detector: str = Field(min_length=1, max_length=120)
    evidence: dict[str, KPIValue] = Field(min_length=1, max_length=10)


class TopologyRelation(InvestigationModel):
    source_cell: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    target_cell: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    enabled: bool


class ThresholdEvidence(InvestigationModel):
    metric: str = Field(min_length=1, max_length=80)
    operator: Literal["minimum", "maximum"]
    value: float
    unit: str = Field(min_length=1, max_length=16)


class CandidateAssessment(InvestigationModel):
    """Deterministic RCA shown only in explicit review mode, never as truth."""

    category: RootCauseCategory
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=800)
    evidence_kpis: dict[str, KPIValue] = Field(max_length=10)
    next_diagnostic_check: str = Field(min_length=1, max_length=400)


class ContextMetadata(InvestigationModel):
    context_version: Literal["observable-context-v1"] = "observable-context-v1"
    prompt_version: Literal["telecom-investigator-v1"] = "telecom-investigator-v1"
    lookback_samples: int = Field(gt=0, le=288)
    evidence_limit: int = Field(gt=0, le=256)
    included_telemetry_samples: int = Field(ge=0, le=256)
    retrieval_limit: int = Field(ge=0, le=12)
    future_telemetry_excluded: Literal[True] = True
    evaluation_truth_excluded: Literal[True] = True


class InvestigationContext(InvestigationModel):
    analyzed_cell: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    analyzed_timestamp: AwareDatetime
    mode: InvestigationMode
    anomaly: ObservableAnomaly
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=256)
    topology_relations: list[TopologyRelation] = Field(max_length=64)
    thresholds: list[ThresholdEvidence] = Field(min_length=1, max_length=20)
    retrieved_knowledge: list[RetrievedKnowledge] = Field(max_length=12)
    candidate_assessment: CandidateAssessment | None = None
    metadata: ContextMetadata

    @model_validator(mode="after")
    def validate_context_identity_and_mode(self) -> InvestigationContext:
        if self.anomaly.cell_id != self.analyzed_cell:
            raise ValueError("anomaly cell must match analyzed cell")
        if self.anomaly.timestamp != self.analyzed_timestamp:
            raise ValueError("anomaly timestamp must match analyzed timestamp")
        if any(item.timestamp > self.analyzed_timestamp for item in self.evidence):
            raise ValueError("investigation evidence cannot contain future telemetry")
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence identifiers must be unique")
        if self.mode is InvestigationMode.INDEPENDENT and self.candidate_assessment is not None:
            raise ValueError("independent mode cannot include a deterministic RCA candidate")
        if self.mode is InvestigationMode.REVIEW and self.candidate_assessment is None:
            raise ValueError("review mode requires a deterministic RCA candidate")
        return self


class Hypothesis(InvestigationModel):
    category: RootCauseCategory
    explanation: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(max_length=12)
    counter_evidence_ids: list[str] = Field(max_length=8)
    knowledge_citations: list[str] = Field(max_length=8)
    missing_evidence: list[str] = Field(max_length=8)
    next_diagnostic_checks: list[str] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validate_references(self) -> Hypothesis:
        for field_name in (
            "supporting_evidence_ids",
            "counter_evidence_ids",
            "knowledge_citations",
            "missing_evidence",
            "next_diagnostic_checks",
        ):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} entries must be unique")
        return self


class InvestigationOutput(InvestigationModel):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=4)
    primary_hypothesis: RootCauseCategory
    abstained: bool
    uncertainty_explanation: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def validate_primary_and_abstention(self) -> InvestigationOutput:
        categories = [item.category for item in self.hypotheses]
        if len(categories) != len(set(categories)):
            raise ValueError("hypothesis categories must be unique")
        if self.primary_hypothesis not in categories:
            raise ValueError("primary hypothesis must be present in hypotheses")
        if self.abstained and self.primary_hypothesis is not RootCauseCategory.UNKNOWN:
            raise ValueError("abstention requires unknown as the primary hypothesis")
        if not self.abstained:
            primary = next(
                item for item in self.hypotheses if item.category is self.primary_hypothesis
            )
            if not primary.supporting_evidence_ids:
                raise ValueError("a non-abstained primary hypothesis requires supporting evidence")
        return self


class ProviderMetadata(InvestigationModel):
    provider: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)
    live_model: bool
    latency_ms: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    temperature: float | None = Field(default=None, ge=0, le=2)


class AIInvestigation(InvestigationModel):
    investigation_id: str = Field(pattern=r"^inv-[a-f0-9]{16}$")
    analyzed_cell: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    analyzed_timestamp: AwareDatetime
    output: InvestigationOutput
    provider: ProviderMetadata
    prompt_version: Literal["telecom-investigator-v1"] = "telecom-investigator-v1"


class VerificationResult(InvestigationModel):
    status: VerificationStatus
    verified_evidence_references: list[str]
    invalid_evidence_references: list[str]
    valid_knowledge_citations: list[str]
    invalid_knowledge_citations: list[str]
    unsupported_claims: list[str]
    confidence_policy_violations: list[str]
    safety_policy_violations: list[str]
    context_binding_violations: list[str]
    usable_for_engineering_review: bool


class InvestigationReport(InvestigationModel):
    context: InvestigationContext
    investigation: AIInvestigation | None
    verification: VerificationResult
    failure_reason: str | None = Field(default=None, max_length=500)
    failure_kind: InvestigationFailureKind | None = None
    advisory_only: Literal[True] = True
    can_modify_shadow_decision: Literal[False] = False

    @model_validator(mode="after")
    def validate_failure_state(self) -> InvestigationReport:
        if (self.failure_reason is None) != (self.failure_kind is None):
            raise ValueError("failure reason and failure kind must be reported together")
        if self.investigation is not None and self.failure_kind is not None:
            raise ValueError("completed investigations cannot report a pipeline failure")
        return self


class ProviderCallResult(InvestigationModel):
    payload: dict[str, Any]
    metadata: ProviderMetadata
