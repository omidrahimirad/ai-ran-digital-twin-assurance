from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ai_ran_assurance.domain.enums import ActionType, RootCauseCategory
from ai_ran_assurance.domain.models import CorrectiveAction, RootCauseDiagnosis


class ActionRecommender:
    """Map diagnoses to vendor-neutral candidate actions for shadow validation."""

    _mapping: dict[RootCauseCategory, tuple[ActionType, dict[str, float | str]]] = {
        RootCauseCategory.CONGESTION: (ActionType.ACTIVATE_CAPACITY, {"capacity_delta_pct": 25.0}),
        RootCauseCategory.INTERFERENCE: (
            ActionType.STEER_TRAFFIC,
            {"traffic_delta_pct": 15.0},
        ),
        RootCauseCategory.NEIGHBOR_RELATION: (
            ActionType.RESTORE_NEIGHBOR,
            {"relation": "best_disabled_or_missing_candidate"},
        ),
        RootCauseCategory.CELL_OUTAGE: (
            ActionType.STEER_TRAFFIC,
            {"traffic_delta_pct": 20.0},
        ),
        RootCauseCategory.TRANSPORT: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.COVERAGE: (
            ActionType.ROLLBACK_PARAMETER,
            {"parameter": "antenna_tilt_deg", "parameter_delta": -2.0},
        ),
        RootCauseCategory.RADIO_QUALITY: (ActionType.HUMAN_REVIEW, {}),
        RootCauseCategory.MOBILITY_CONFIGURATION: (
            ActionType.ROLLBACK_PARAMETER,
            {"parameter": "handover_margin_db", "parameter_delta": -2.0},
        ),
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
            parameters=parameters,
            rationale=(
                f"Shadow-mode candidate for diagnosed {diagnosis.probable_root_cause.value}; "
                "no command will be sent to a network."
            ),
            proposed_at=timestamp,
        )
