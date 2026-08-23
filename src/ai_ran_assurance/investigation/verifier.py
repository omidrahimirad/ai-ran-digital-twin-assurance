"""Deterministic grounding, confidence, and safety verifier."""

from __future__ import annotations

from ai_ran_assurance.config import InvestigationSettings
from ai_ran_assurance.investigation.models import (
    AIInvestigation,
    InvestigationContext,
    VerificationResult,
    VerificationStatus,
)
from ai_ran_assurance.investigation.policy import (
    unsafe_actuation_claims,
    unsupported_observation_claims,
)


class EvidenceVerifier:
    def __init__(self, settings: InvestigationSettings) -> None:
        self.settings = settings

    def verify(
        self, context: InvestigationContext, investigation: AIInvestigation
    ) -> VerificationResult:
        evidence_ids = {item.evidence_id for item in context.evidence}
        knowledge_ids = {item.chunk_id for item in context.retrieved_knowledge}
        cited_evidence = {
            reference
            for hypothesis in investigation.output.hypotheses
            for reference in (hypothesis.supporting_evidence_ids + hypothesis.counter_evidence_ids)
        }
        cited_knowledge = {
            reference
            for hypothesis in investigation.output.hypotheses
            for reference in hypothesis.knowledge_citations
        }
        invalid_evidence = sorted(cited_evidence - evidence_ids)
        invalid_knowledge = sorted(cited_knowledge - knowledge_ids)
        context_binding: list[str] = []
        if investigation.analyzed_cell != context.analyzed_cell:
            context_binding.append("investigation cell does not match context")
        if investigation.analyzed_timestamp != context.analyzed_timestamp:
            context_binding.append("investigation timestamp does not match context")
        confidence_violations: list[str] = []
        for hypothesis in investigation.output.hypotheses:
            valid_support = set(hypothesis.supporting_evidence_ids) & evidence_ids
            if (
                hypothesis.confidence >= self.settings.high_confidence_threshold
                and len(valid_support) < self.settings.min_supporting_evidence
            ):
                confidence_violations.append(
                    f"{hypothesis.category.value} confidence {hypothesis.confidence:.2f} "
                    f"has only {len(valid_support)} valid supporting evidence references"
                )

        explanations = [item.explanation for item in investigation.output.hypotheses]
        generated_text = [investigation.output.uncertainty_explanation]
        generated_text.extend(explanations)
        for hypothesis in investigation.output.hypotheses:
            generated_text.extend(hypothesis.missing_evidence)
            generated_text.extend(hypothesis.next_diagnostic_checks)
        unsupported = unsupported_observation_claims(explanations)
        safety = unsafe_actuation_claims(generated_text)
        hard_rejection = bool(
            invalid_evidence or invalid_knowledge or safety or context_binding or unsupported
        )
        if hard_rejection:
            status = VerificationStatus.REJECTED
        elif investigation.output.abstained:
            status = VerificationStatus.ABSTAINED
        elif confidence_violations:
            status = VerificationStatus.PARTIALLY_VERIFIED
        else:
            status = VerificationStatus.VERIFIED
        return VerificationResult(
            status=status,
            verified_evidence_references=sorted(cited_evidence & evidence_ids),
            invalid_evidence_references=invalid_evidence,
            valid_knowledge_citations=sorted(cited_knowledge & knowledge_ids),
            invalid_knowledge_citations=invalid_knowledge,
            unsupported_claims=unsupported,
            confidence_policy_violations=confidence_violations,
            safety_policy_violations=safety,
            context_binding_violations=context_binding,
            usable_for_engineering_review=status
            in {
                VerificationStatus.VERIFIED,
                VerificationStatus.PARTIALLY_VERIFIED,
                VerificationStatus.ABSTAINED,
            },
        )


def rejected_verification(reason: str) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.REJECTED,
        verified_evidence_references=[],
        invalid_evidence_references=[],
        valid_knowledge_citations=[],
        invalid_knowledge_citations=[],
        unsupported_claims=[reason],
        confidence_policy_violations=[],
        safety_policy_violations=[],
        context_binding_violations=[],
        usable_for_engineering_review=False,
    )
