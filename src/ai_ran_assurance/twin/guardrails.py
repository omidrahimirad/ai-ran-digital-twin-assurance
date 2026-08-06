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
    """Fail-closed policy checks; approval remains shadow-report-only."""

    def __init__(self, settings: ThresholdSettings) -> None:
        self.settings = settings

    def _check_cell(
        self,
        label: str,
        before: dict[str, float],
        predicted: dict[str, float],
        violations: list[str],
    ) -> None:
        prefix = f"{label}: "
        if predicted["handover_success_pct"] < self.settings.handover_success_min_pct:
            violations.append(prefix + "predicted handover success is below threshold")
        if predicted["rrc_success_pct"] < self.settings.rrc_success_min_pct:
            violations.append(prefix + "predicted RRC success is below threshold")
        if predicted["availability_pct"] < self.settings.availability_min_pct:
            violations.append(prefix + "predicted availability is below threshold")
        availability_drop = before["availability_pct"] - predicted["availability_pct"]
        if availability_drop > self.settings.availability_max_drop_pct:
            violations.append(prefix + "predicted availability decrease exceeds the limit")
        if predicted["latency_ms"] > self.settings.latency_max_ms:
            violations.append(prefix + "predicted latency exceeds threshold")
        if predicted["call_drop_pct"] > self.settings.call_drop_max_pct:
            violations.append(prefix + "predicted call-drop rate exceeds threshold")
        if predicted["bler_pct"] > self.settings.bler_max_pct:
            violations.append(prefix + "predicted BLER exceeds threshold")

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
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if telemetry_timestamp.tzinfo is None or telemetry_timestamp.utcoffset() is None:
            raise ValueError("telemetry_timestamp must be timezone-aware")
        if action.action_id != prediction.action_id:
            violations.append("action and prediction identifiers do not match")
        if action.cell_id != prediction.cell_id:
            violations.append("action and prediction cells do not match")

        self._check_cell(
            action.cell_id,
            prediction.before_kpis,
            prediction.predicted_kpis,
            violations,
        )
        for cell_id, predicted in prediction.impacted_cell_kpis.items():
            self._check_cell(
                cell_id,
                prediction.impacted_cell_before_kpis[cell_id],
                predicted,
                violations,
            )

        if action.action_type is ActionType.ROLLBACK_PARAMETER:
            delta = abs(
                float(action.parameters["previous_value"])
                - float(action.parameters["current_value"])
            )
            if delta > self.settings.max_parameter_delta:
                violations.append("configuration parameter delta exceeds the allowed limit")
        if action.action_type is ActionType.STEER_TRAFFIC and (
            float(action.parameters["traffic_delta_pct"]) > self.settings.max_traffic_steering_pct
        ):
            violations.append("traffic-steering percentage exceeds the allowed limit")
        if action.action_type is ActionType.ACTIVATE_CAPACITY and (
            float(action.parameters["capacity_delta_pct"]) > self.settings.max_capacity_increase_pct
        ):
            violations.append("capacity increase exceeds the allowed limit")

        cooldown = timedelta(minutes=self.settings.cooldown_minutes)
        for previous in action_history or []:
            elapsed = now - previous.proposed_at
            if elapsed < timedelta(0):
                violations.append("action history contains a future timestamp")
                break
            if (
                previous.cell_id == action.cell_id
                and previous.action_type == action.action_type
                and elapsed < cooldown
            ):
                violations.append("same action is inside the configured cooldown period")
                break

        future_skew = timedelta(seconds=self.settings.max_telemetry_future_skew_seconds)
        age = now - telemetry_timestamp
        if age < -future_skew:
            violations.append("telemetry timestamp is unacceptably far in the future")
        elif age > timedelta(minutes=self.settings.telemetry_max_age_minutes):
            violations.append("telemetry is stale")
        if action.proposed_at < telemetry_timestamp:
            violations.append("action was proposed before its telemetry evidence")
        if action.proposed_at - now > future_skew:
            violations.append("action proposal timestamp is unacceptably far in the future")
        if action.diagnosis_confidence < self.settings.diagnosis_confidence_min:
            violations.append("diagnosis confidence is below the required minimum")
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
        note="Shadow report only. No command was or can be sent to a real RAN.",
    )
