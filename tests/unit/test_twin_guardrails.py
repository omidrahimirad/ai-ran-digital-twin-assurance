from datetime import timedelta

import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.domain.enums import ActionType, DecisionStatus, RootCauseCategory
from ai_ran_assurance.domain.models import RootCauseDiagnosis
from ai_ran_assurance.simulation import KPIGenerator, build_network
from ai_ran_assurance.twin import (
    ActionRecommender,
    GuardrailValidator,
    NetworkTwin,
    TwinSimulator,
    shadow_decision,
)


def _diagnosis(sample: object, cause: RootCauseCategory) -> RootCauseDiagnosis:
    return RootCauseDiagnosis(
        cell_id=sample.cell_id,
        timestamp=sample.timestamp,
        probable_root_cause=cause,
        confidence=0.9,
        evidence_kpis={},
        explanation="test diagnosis",
        next_diagnostic_check="test next check",
    )


@pytest.mark.parametrize("cause", list(RootCauseCategory))
def test_recommender_and_twin_support_every_action(
    project_config: ProjectConfig, cause: RootCauseCategory
) -> None:
    topology = build_network(project_config.network)
    sample = KPIGenerator(topology, project_config.network).generate(1)[0]
    action = ActionRecommender().recommend(_diagnosis(sample, cause), proposed_at=sample.timestamp)
    twin = NetworkTwin(topology, [sample])
    prediction = TwinSimulator().simulate(twin, action)
    assert prediction.action_id == action.action_id
    assert prediction.model_description.startswith("Deterministic")
    assert set(prediction.before_kpis) == set(prediction.predicted_kpis)


def test_twin_copy_neighbor_restore_and_unknown_cell(project_config: ProjectConfig) -> None:
    topology = build_network(project_config.network)
    sample = KPIGenerator(topology, project_config.network).generate(1)[0]
    twin = NetworkTwin(topology, [sample])
    copied = twin.copy()
    assert copied is not twin
    initial = len(twin.neighbors(sample.cell_id))
    assert twin.restore_neighbor(sample.cell_id) is not None
    assert len(twin.neighbors(sample.cell_id)) == initial + 1
    with pytest.raises(ValueError, match="unknown cell"):
        twin.sample("NO-CELL")


def test_guardrails_approve_safe_and_reject_all_unsafe_classes(
    project_config: ProjectConfig,
) -> None:
    topology = build_network(project_config.network)
    samples = KPIGenerator(topology, project_config.network).generate(
        60, project_config.scenario("congestion"), seed=43
    )
    sample = [item for item in samples if item.ground_truth is RootCauseCategory.CONGESTION][-1]
    action = ActionRecommender().recommend(
        _diagnosis(sample, RootCauseCategory.CONGESTION), proposed_at=sample.timestamp
    )
    prediction = TwinSimulator().simulate(NetworkTwin(topology, [sample]), action)
    validator = GuardrailValidator(project_config.thresholds)
    safe = validator.validate(
        action, prediction, telemetry_timestamp=sample.timestamp, evaluated_at=sample.timestamp
    )
    assert safe.approved
    assert shadow_decision(action, prediction, safe).status is DecisionStatus.SHADOW_APPROVED

    unsafe_kpis = prediction.predicted_kpis | {
        "handover_success_pct": 80,
        "rrc_success_pct": 90,
        "availability_pct": prediction.before_kpis["availability_pct"] - 2,
        "latency_ms": 120,
    }
    unsafe_prediction = prediction.model_copy(
        update={"predicted_kpis": unsafe_kpis, "confidence": 0.1}
    )
    unsafe_action = action.model_copy(update={"parameters": {"parameter_delta": 99}})
    previous = action.model_copy(update={"proposed_at": sample.timestamp - timedelta(minutes=1)})
    rejected = validator.validate(
        unsafe_action,
        unsafe_prediction,
        telemetry_timestamp=sample.timestamp - timedelta(hours=1),
        evaluated_at=sample.timestamp,
        action_history=[previous],
    )
    assert not rejected.approved
    assert len(rejected.violations) == 8
    assert (
        shadow_decision(unsafe_action, unsafe_prediction, rejected).status
        is DecisionStatus.SHADOW_REJECTED
    )

    review = action.model_copy(update={"action_type": ActionType.HUMAN_REVIEW})
    review_result = validator.validate(
        review, prediction, telemetry_timestamp=sample.timestamp, evaluated_at=sample.timestamp
    )
    assert shadow_decision(review, prediction, review_result).status is DecisionStatus.HUMAN_REVIEW
