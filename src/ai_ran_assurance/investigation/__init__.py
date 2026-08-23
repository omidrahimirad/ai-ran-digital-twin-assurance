"""Optional, advisory, evidence-grounded RAN investigation layer."""

from ai_ran_assurance.investigation.context import (
    InvestigationContextBuilder,
    select_anomaly,
)
from ai_ran_assurance.investigation.investigator import (
    AIInvestigator,
    InvestigationService,
    default_retriever,
    provider_from_name,
)
from ai_ran_assurance.investigation.models import (
    AIInvestigation,
    EvidenceItem,
    Hypothesis,
    InvestigationContext,
    InvestigationFailureKind,
    InvestigationMode,
    InvestigationReport,
    RetrievedKnowledge,
    VerificationResult,
    VerificationStatus,
)
from ai_ran_assurance.investigation.providers import (
    FixtureProvider,
    InvestigationProvider,
    OpenAIResponsesProvider,
    ProviderError,
    ProviderUnavailableError,
)
from ai_ran_assurance.investigation.retrieval import LexicalRetriever
from ai_ran_assurance.investigation.verifier import EvidenceVerifier

__all__ = [
    "AIInvestigation",
    "AIInvestigator",
    "EvidenceItem",
    "EvidenceVerifier",
    "FixtureProvider",
    "Hypothesis",
    "InvestigationContext",
    "InvestigationContextBuilder",
    "InvestigationFailureKind",
    "InvestigationMode",
    "InvestigationProvider",
    "InvestigationReport",
    "InvestigationService",
    "LexicalRetriever",
    "OpenAIResponsesProvider",
    "ProviderError",
    "ProviderUnavailableError",
    "RetrievedKnowledge",
    "VerificationResult",
    "VerificationStatus",
    "default_retriever",
    "provider_from_name",
    "select_anomaly",
]
