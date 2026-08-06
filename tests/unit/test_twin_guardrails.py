from datetime import timedelta
from typing import Any

import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.domain.enums import ActionType, DecisionStatus, RootCauseCategory
from ai_ran_assurance.domain.models import (
    CorrectiveAction,
    KPISample,
    NetworkTopology,
    RootCauseDiagnosis,
)
from ai_ran_assurance.simulation import KPIGenerator, build_network
from ai_ran_assurance.twin import (
    ActionRecommender,
    ActionSimulationError,
    GuardrailValidator,
    NetworkTwin,
    TwinSimulator,
    shadow_decision,
)


def _validated_copy(model: Any, **updates: Any) -> Any:
    values = model.model_dump()
    values.update(updates)
    return type(model).model_validate(values)


def _diagnosis(sample: KPISample, cause: RootCauseCategory) -> RootCauseDiagnosis:
    return RootCauseDiagnosis(
        cell_id=sample.cell_id,
        timestamp=sample.timestamp,
        probable_root_cause=cause,
        confidence=0.9,
        evidence_kpis={},
        explanation="test diagnosis",
        next_diagnostic_check="test next check",
    )


def _action(
    sample: KPISample,
    action_type: ActionType,
    parameters: dict[str, object],
    *,
    confidence: float = 0.9,
) -> CorrectiveAction:
    return CorrectiveAction(
        action_id=f"test-{action_type.value}",
        cell_id=sample.cell_id,
        action_type=action_type,
        parameters=parameters,
        diagnosis_confidence=confidence,
        rationale="test shadow candidate",
        proposed_at=sample.timestamp,
    )


def _state(
    project_config: ProjectConfig, scenario_name: str = "congestion"
) -> tuple[NetworkTopology, list[KPISample]]:
    topology = build_network(project_config.network)
    scenario = project_config.scenario(scenario_name)
    samples = KPIGenerator(topology, project_config.network).generate(
        scenario.start_step + 2, scenario, seed=43
    )
    timestamp = next(
        item.timestamp
        for item in samples
        if item.cell_id == scenario.target_cells[0] and item.step == scenario.start_step + 1
    )
    return topology, [item for item in samples if item.timestamp == timestamp]


@pytest.mark.parametrize("cause", list(RootCauseCategory))
def test_recommender_is_conservative(
    project_config: ProjectConfig, cause: RootCauseCategory
) -> None:
    topology = build_network(project_config.network)
    sample = KPIGenerator(topology, project_config.network).generate(1)[0]
    action = ActionRecommender().recommend(_diagnosis(sample, cause), proposed_at=sample.timestamp)
    assert action.action_type is (
        ActionType.ACTIVATE_CAPACITY
        if cause is RootCauseCategory.CONGESTION
        else ActionType.HUMAN_REVIEW
    )
    prediction = TwinSimulator().simulate(NetworkTwin(topology, [sample]), action)
    assert prediction.action_id == action.action_id
    assert prediction.model_description.startswith("Bounded deterministic response surrogate")
    assert set(prediction.before_kpis) == set(prediction.predicted_kpis)


def test_twin_requires_consistent_known_timestamp_state(project_config: ProjectConfig) -> None:
    topology = build_network(project_config.network)
    samples = KPIGenerator(topology, project_config.network).generate(2)
    first = samples[0]
    same_time = [item for item in samples if item.timestamp == first.timestamp]
    twin = NetworkTwin(topology, same_time)
    assert twin.copy() is not twin
    with pytest.raises(ValueError, match="one sample per cell"):
        NetworkTwin(topology, [first, first])
    with pytest.raises(ValueError, match="one timestamp"):
        NetworkTwin(topology, [samples[0], samples[-1]])
    with pytest.raises(ValueError, match="unknown cells"):
        NetworkTwin(topology, [_validated_copy(first, cell_id="CELL-999")])
    with pytest.raises(ValueError, match="cannot be empty"):
        NetworkTwin(topology, [])
    with pytest.raises(ValueError, match="unknown cell"):
        twin.sample("CELL-999")


def test_neighbor_restore_only_enables_an_existing_disabled_relation(
    project_config: ProjectConfig,
) -> None:
    topology = build_network(project_config.network)
    relation = topology.neighbor_relations[0]
    relation.enabled = False
    samples = KPIGenerator(topology, project_config.network).generate(1)
    twin = NetworkTwin(topology, samples)
    assert relation.target_cell not in twin.neighbors(relation.source_cell)
    twin.restore_neighbor(relation.source_cell, relation.target_cell)
    assert relation.target_cell in twin.neighbors(relation.source_cell)
    with pytest.raises(ValueError, match="already enabled"):
        twin.restore_neighbor(relation.source_cell, relation.target_cell)
    nonexistent = next(
        cell.cell_id
        for cell in topology.cells
        if cell.cell_id != relation.source_cell
        and all(
            item.source_cell != relation.source_cell or item.target_cell != cell.cell_id
            for item in topology.neighbor_relations
        )
    )
    with pytest.raises(ValueError, match="does not exist"):
        twin.restore_neighbor(relation.source_cell, nonexistent)


def test_capacity_and_traffic_models_are_bounded_and_include_impacted_cell(
    project_config: ProjectConfig,
) -> None:
    topology, samples = _state(project_config)
    target_id = project_config.scenario("congestion").target_cells[0]
    sample = next(item for item in samples if item.cell_id == target_id)
    capacity = _action(sample, ActionType.ACTIVATE_CAPACITY, {"capacity_delta_pct": 15.0})
    capacity_prediction = TwinSimulator().simulate(NetworkTwin(topology, samples), capacity)
    assert capacity_prediction.predicted_kpis["prb_utilization_pct"] < sample.prb_utilization_pct
    assert capacity_prediction.predicted_kpis["latency_ms"] <= sample.latency_ms
    assert capacity_prediction.predicted_kpis["throughput_mbps"] <= (sample.throughput_mbps * 1.08)
    assert capacity_prediction.confidence < 0.65

    neighbor = NetworkTwin(topology, samples).neighbors(sample.cell_id)[0]
    steering = _action(
        sample,
        ActionType.STEER_TRAFFIC,
        {"target_cell": neighbor, "traffic_delta_pct": 10.0},
    )
    steering_prediction = TwinSimulator().simulate(NetworkTwin(topology, samples), steering)
    assert set(steering_prediction.impacted_cell_kpis) == {neighbor}
    assert steering_prediction.predicted_kpis["prb_utilization_pct"] < sample.prb_utilization_pct
    assert (
        steering_prediction.impacted_cell_kpis[neighbor]["prb_utilization_pct"]
        > (steering_prediction.impacted_cell_before_kpis[neighbor]["prb_utilization_pct"])
    )
    unsafe_target = steering_prediction.impacted_cell_kpis[neighbor] | {"latency_ms": 120}
    unsafe_steering = _validated_copy(
        steering_prediction,
        impacted_cell_kpis={neighbor: unsafe_target},
        confidence=0.9,
    )
    rejected = GuardrailValidator(project_config.thresholds).validate(
        steering,
        unsafe_steering,
        telemetry_timestamp=sample.timestamp,
        evaluated_at=sample.timestamp,
    )
    assert f"{neighbor}: predicted latency exceeds threshold" in rejected.violations


def test_simulator_rejects_unsupported_or_inconsistent_actions(
    project_config: ProjectConfig,
) -> None:
    topology, samples = _state(project_config)
    sample = samples[0]
    twin = NetworkTwin(topology, samples)
    non_neighbor = next(
        cell.cell_id
        for cell in topology.cells
        if cell.cell_id != sample.cell_id and cell.cell_id not in twin.neighbors(sample.cell_id)
    )
    steering = _action(
        sample,
        ActionType.STEER_TRAFFIC,
        {"target_cell": non_neighbor, "traffic_delta_pct": 10},
    )
    with pytest.raises(ActionSimulationError, match="not an enabled neighbor"):
        TwinSimulator().simulate(twin, steering)

    neighbor = twin.neighbors(sample.cell_id)[0]
    overloaded_samples = [
        _validated_copy(item, prb_utilization_pct=94) if item.cell_id == neighbor else item
        for item in samples
    ]
    overloaded_steering = _action(
        sample,
        ActionType.STEER_TRAFFIC,
        {"target_cell": neighbor, "traffic_delta_pct": 10},
    )
    with pytest.raises(ActionSimulationError, match="lacks modeled PRB headroom"):
        TwinSimulator().simulate(NetworkTwin(topology, overloaded_samples), overloaded_steering)

    rollback = _action(
        sample,
        ActionType.ROLLBACK_PARAMETER,
        {"parameter": "handover_margin_db", "current_value": 4, "previous_value": 3},
    )
    with pytest.raises(ActionSimulationError, match="does not match"):
        TwinSimulator().simulate(twin, rollback)

    restore = _action(
        sample,
        ActionType.RESTORE_NEIGHBOR,
        {"target_cell": non_neighbor},
    )
    with pytest.raises(ValueError, match="does not exist"):
        TwinSimulator().simulate(twin, restore)


def test_restore_and_rollback_effects_are_small_and_low_confidence(
    project_config: ProjectConfig,
) -> None:
    topology = build_network(project_config.network)
    relation = topology.neighbor_relations[0]
    relation.enabled = False
    samples = KPIGenerator(topology, project_config.network).generate(1)
    source = next(item for item in samples if item.cell_id == relation.source_cell)
    restore = _action(
        source,
        ActionType.RESTORE_NEIGHBOR,
        {"target_cell": relation.target_cell},
    )
    restored = TwinSimulator().simulate(NetworkTwin(topology, samples), restore)
    assert restored.predicted_kpis["handover_success_pct"] <= (
        restored.before_kpis["handover_success_pct"] + 2
    )
    assert restored.predicted_kpis["call_drop_pct"] >= max(
        0, restored.before_kpis["call_drop_pct"] - 0.35
    )
    assert restored.confidence < project_config.thresholds.prediction_confidence_min

    current_margin = next(
        cell.configuration.handover_margin_db
        for cell in topology.cells
        if cell.cell_id == source.cell_id
    )
    rollback = _action(
        source,
        ActionType.ROLLBACK_PARAMETER,
        {
            "parameter": "handover_margin_db",
            "current_value": current_margin,
            "previous_value": current_margin - 1,
        },
    )
    rolled_back = TwinSimulator().simulate(NetworkTwin(topology, samples), rollback)
    assert (
        0
        < rolled_back.predicted_kpis["handover_success_pct"]
        - rolled_back.before_kpis["handover_success_pct"]
        <= 0.5
    )
    assert rolled_back.confidence < project_config.thresholds.prediction_confidence_min


def test_guardrails_fail_closed_for_kpis_identity_freshness_and_confidence(
    project_config: ProjectConfig,
) -> None:
    topology, samples = _state(project_config)
    target = project_config.scenario("congestion").target_cells[0]
    sample = next(item for item in samples if item.cell_id == target)
    action = _action(sample, ActionType.ACTIVATE_CAPACITY, {"capacity_delta_pct": 15})
    prediction = TwinSimulator().simulate(NetworkTwin(topology, samples), action)
    prediction = _validated_copy(prediction, confidence=0.9)
    validator = GuardrailValidator(project_config.thresholds)

    safe = validator.validate(
        action, prediction, telemetry_timestamp=sample.timestamp, evaluated_at=sample.timestamp
    )
    assert safe.approved
    assert shadow_decision(action, prediction, safe).status is DecisionStatus.SHADOW_APPROVED

    unsafe_kpis = prediction.predicted_kpis | {
        "handover_success_pct": 80,
        "rrc_success_pct": 90,
        "availability_pct": 98,
        "latency_ms": 120,
        "call_drop_pct": 5,
        "bler_pct": 25,
    }
    unsafe_prediction = _validated_copy(
        prediction,
        action_id="wrong-id",
        cell_id="CELL-020",
        predicted_kpis=unsafe_kpis,
        confidence=0.1,
    )
    excessive = _validated_copy(action, parameters={"capacity_delta_pct": 31})
    previous = _validated_copy(action, proposed_at=sample.timestamp - timedelta(minutes=1))
    rejected = validator.validate(
        excessive,
        unsafe_prediction,
        telemetry_timestamp=sample.timestamp - timedelta(hours=1),
        evaluated_at=sample.timestamp,
        action_history=[previous],
    )
    assert not rejected.approved
    combined = " | ".join(rejected.violations)
    for expected in (
        "identifiers do not match",
        "cells do not match",
        "handover success",
        "RRC success",
        "availability is below",
        "latency exceeds",
        "call-drop",
        "BLER",
        "capacity increase",
        "cooldown",
        "telemetry is stale",
        "prediction confidence",
    ):
        assert expected in combined
    matched_low_confidence = _validated_copy(prediction, confidence=0.1)
    matched_rejection = validator.validate(
        action,
        matched_low_confidence,
        telemetry_timestamp=sample.timestamp,
        evaluated_at=sample.timestamp,
    )
    assert (
        shadow_decision(action, matched_low_confidence, matched_rejection).status
        is DecisionStatus.SHADOW_REJECTED
    )


def test_guardrails_reject_future_and_low_confidence_human_decisions(
    project_config: ProjectConfig,
) -> None:
    topology, samples = _state(project_config)
    sample = samples[0]
    review = _action(
        sample,
        ActionType.HUMAN_REVIEW,
        {},
        confidence=0.2,
    )
    prediction = TwinSimulator().simulate(NetworkTwin(topology, samples), review)
    evaluated_at = sample.timestamp
    future_data = sample.timestamp + timedelta(minutes=1)
    result = GuardrailValidator(project_config.thresholds).validate(
        review,
        prediction,
        telemetry_timestamp=future_data,
        evaluated_at=evaluated_at,
    )
    assert not result.approved
    combined = " | ".join(result.violations)
    assert "telemetry timestamp is unacceptably far in the future" in combined
    assert "proposed before its telemetry" in combined
    assert "diagnosis confidence" in combined
    assert "prediction confidence" in combined
    assert "human review" in combined
    assert shadow_decision(review, prediction, result).status is DecisionStatus.HUMAN_REVIEW
