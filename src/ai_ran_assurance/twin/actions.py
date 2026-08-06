from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ai_ran_assurance.domain.enums import ActionType, RootCauseCategory
from ai_ran_assurance.domain.models import CorrectiveAction, RootCauseDiagnosis


class ActionRecommender:
    """Map diagnoses to vendor-neutral candidate actions for shadow validation."""

    _mapping: dict[RootCauseCategory, tuple[ActionType, dict[str, float | str]]] = {
        RootCauseCategory.CONGESTION: (ActionType.ACTIVATE_CAPACITY, {"capacity_delta_pct": 15.0}),
        RootCauseCategory.INTERFERENCE: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.NEIGHBOR_RELATION: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.CELL_OUTAGE: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.TRANSPORT: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.COVERAGE: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.RADIO_QUALITY: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.MOBILITY_CONFIGURATION: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.UNKNOWN: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.NORMAL: (ActionType.HUMAN_REVIEW, {}),
    }

    def recommend(
        self, diagnosis: RootCauseDiagnosis, *, proposed_at: datetime | None = None
    ) -> CorrectiveAction:
        action_type, parameters = self._mapping[diagnosis.probable_root_cause]
        timestamp = proposed_at or datetime.now(UTC)
        identifier = uuid5(
            NAMESPACE_URL,
            f"{diagnosis.cell_id}:{diagnosis.timestamp.isoformat()}:{action_type.value}",
        )
        return CorrectiveAction(
            action_id=str(identifier),
            cell_id=diagnosis.cell_id,
            action_type=action_type,
            parameters=parameters.copy(),
            diagnosis_confidence=diagnosis.confidence,
            rationale=(
                f"Shadow-mode candidate for diagnosed {diagnosis.probable_root_cause.value}; "
                "no command will be sent to a network."
            ),
            proposed_at=timestamp,
        )
