"""Metrics and error taxonomy for advisory investigation evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.investigation.models import (
    InvestigationFailureKind,
    InvestigationReport,
    VerificationStatus,
)


@dataclass(frozen=True)
class ScoredInvestigation:
    expected: RootCauseCategory
    ambiguous: bool
    report: InvestigationReport


def classify_error(case: ScoredInvestigation) -> str:
    report = case.report
    if report.investigation is None:
        return "provider_or_schema_failure"
    verification = report.verification
    if verification.safety_policy_violations:
        return "unsafe_action_suggestion"
    if verification.invalid_evidence_references:
        return "invalid_evidence_reference"
    if verification.invalid_knowledge_citations:
        return "invalid_knowledge_citation"
    if verification.unsupported_claims:
        return "unsupported_observation"
    output = report.investigation.output
    if case.ambiguous and not output.abstained:
        return "ambiguous_case_overclaimed"
    if not case.ambiguous and output.abstained:
        return "unnecessary_abstention"
    if output.primary_hypothesis is not case.expected and not case.ambiguous:
        return "correct_evidence_wrong_rca"
    if verification.confidence_policy_violations:
        return "insufficient_support_overconfident"
    if not report.context.retrieved_knowledge:
        return "retrieval_empty"
    return "none"


def investigation_metrics(cases: list[ScoredInvestigation]) -> dict[str, float | int]:
    if not cases:
        raise ValueError("at least one investigation case is required")
    completed = [
        (case, case.report.investigation.output)
        for case in cases
        if case.report.investigation is not None
    ]
    ambiguous = [(case, output) for case, output in completed if case.ambiguous]
    nonambiguous = [(case, output) for case, output in completed if not case.ambiguous]
    strict_correct = sum(
        case.report.investigation is not None
        and case.report.investigation.output.primary_hypothesis is case.expected
        for case in cases
    )
    nonambiguous_correct = sum(
        output.primary_hypothesis is case.expected for case, output in nonambiguous
    )
    abstained = sum(output.abstained for _, output in completed)
    ambiguity_respected = sum(output.abstained for _, output in ambiguous)
    evidence_valid = sum(
        len(case.report.verification.verified_evidence_references) for case in cases
    )
    evidence_invalid = sum(
        len(case.report.verification.invalid_evidence_references) for case in cases
    )
    citations_valid = sum(len(case.report.verification.valid_knowledge_citations) for case in cases)
    citations_invalid = sum(
        len(case.report.verification.invalid_knowledge_citations) for case in cases
    )
    return {
        "case_count": len(cases),
        "completed_investigations": len(completed),
        "strict_top1_accuracy_all_cases": round(strict_correct / len(cases), 6),
        "top1_accuracy_nonambiguous_cases": (
            round(nonambiguous_correct / len(nonambiguous), 6) if nonambiguous else 0.0
        ),
        "unknown_or_abstention_rate": round(abstained / len(cases), 6),
        "ambiguity_respect_rate": (
            round(ambiguity_respected / len(ambiguous), 6) if ambiguous else 0.0
        ),
        "ambiguous_overclaim_rate": (
            round((len(ambiguous) - ambiguity_respected) / len(ambiguous), 6) if ambiguous else 0.0
        ),
        "evidence_reference_validity_rate": (
            round(evidence_valid / (evidence_valid + evidence_invalid), 6)
            if evidence_valid + evidence_invalid
            else 0.0
        ),
        "knowledge_citation_validity_rate": (
            round(citations_valid / (citations_valid + citations_invalid), 6)
            if citations_valid + citations_invalid
            else 0.0
        ),
        "unsupported_evidence_reference_rate": (
            round(evidence_invalid / (evidence_valid + evidence_invalid), 6)
            if evidence_valid + evidence_invalid
            else 0.0
        ),
        "verifier_rejection_rate": round(
            sum(case.report.verification.status is VerificationStatus.REJECTED for case in cases)
            / len(cases),
            6,
        ),
        "unsafe_action_suggestion_violations": sum(
            bool(case.report.verification.safety_policy_violations) for case in cases
        ),
        "structured_or_provider_failures": len(cases) - len(completed),
        "provider_failure_rate": round(
            sum(case.report.failure_kind is InvestigationFailureKind.PROVIDER for case in cases)
            / len(cases),
            6,
        ),
        "schema_validation_failure_rate": round(
            sum(
                case.report.failure_kind is InvestigationFailureKind.SCHEMA_VALIDATION
                for case in cases
            )
            / len(cases),
            6,
        ),
    }
