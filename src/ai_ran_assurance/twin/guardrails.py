from datetime import UTC, datetime, timedelta

from ai_ran_assurance.config import ThresholdSettings
from ai_ran_assurance.domain.enums import ActionType, DecisionStatus
from ai_ran_assurance.domain.models import (
    CorrectiveAction,
    GuardrailResult,
    ShadowDecision,
    TwinPrediction,
)


class GuardrailValidator:
    """Policy checks for candidate actions; approval remains shadow-only."""

    def __init__(self, settings: ThresholdSettings) -> None:
        self.settings = settings

    def validate(
        self,
        action: CorrectiveAction,
        prediction: TwinPrediction,
        *,
        telemetry_timestamp: datetime,
        evaluated_at: datetime | None = None,
        action_history: list[CorrectiveAction] | None = None,
    ) -> GuardrailResult:
        now = evaluated_at or datetime.now(UTC)
        violations: list[str] = []
        predicted = prediction.predicted_kpis
        before = prediction.before_kpis
        if predicted["handover_success_pct"] < self.settings.handover_success_min_pct:
            violations.append("predicted handover success is below the safety threshold")
        if predicted["rrc_success_pct"] < self.settings.rrc_success_min_pct:
            violations.append("predicted RRC success is below the safety threshold")
        availability_drop = before["availability_pct"] - predicted["availability_pct"]
        if availability_drop > self.settings.availability_max_drop_pct:
            violations.append("predicted availability decrease exceeds the allowed threshold")
        if predicted["latency_ms"] > self.settings.latency_max_ms:
            violations.append("predicted latency exceeds the safety threshold")
        delta = abs(float(action.parameters.get("parameter_delta", 0.0)))
        if delta > self.settings.max_parameter_delta:
            violations.append("configuration parameter delta exceeds the allowed limit")
        cooldown = timedelta(minutes=self.settings.cooldown_minutes)
        for previous in action_history or []:
            if (
                previous.cell_id == action.cell_id
                and previous.action_type == action.action_type
                and now - previous.proposed_at < cooldown
            ):
                violations.append("same action is inside the configured cooldown period")
                break
        age = now - telemetry_timestamp
        if age > timedelta(minutes=self.settings.telemetry_max_age_minutes):
            violations.append("telemetry is stale")
        if prediction.confidence < self.settings.prediction_confidence_min:
            violations.append("prediction confidence is below the required minimum")
        if action.action_type is ActionType.HUMAN_REVIEW:
            violations.append("candidate explicitly requests human review")
        return GuardrailResult(
            approved=not violations,
            violations=violations,
            evaluated_at=now,
        )


def shadow_decision(
    action: CorrectiveAction,
    prediction: TwinPrediction,
    guardrail: GuardrailResult,
) -> ShadowDecision:
    if action.action_type is ActionType.HUMAN_REVIEW:
        status = DecisionStatus.HUMAN_REVIEW
    elif guardrail.approved:
        status = DecisionStatus.SHADOW_APPROVED
    else:
        status = DecisionStatus.SHADOW_REJECTED
    return ShadowDecision(
        action=action,
        prediction=prediction,
        guardrail=guardrail,
        status=status,
        note="Shadow-mode report only. No command was or can be sent to a real RAN.",
    )
