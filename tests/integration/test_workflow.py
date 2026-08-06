import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.domain.enums import ActionType, RootCauseCategory
from ai_ran_assurance.domain.models import Anomaly
from ai_ran_assurance.workflow import ClosedLoopEngine


@pytest.mark.parametrize(
    "scenario_name",
    [
        "congestion",
        "interference",
        "missing_neighbor",
        "outage",
        "transport_latency",
        "coverage",
        "bler",
        "mobility",
    ],
)
def test_each_scenario_completes_closed_loop(
    closed_loop: ClosedLoopEngine, scenario_name: str
) -> None:
    result = closed_loop.run(scenario_name)
    assert result.telemetry
    assert result.anomalies
    target = result.scenario.target_cells[0]
    diagnosis = next(item for item in result.diagnoses if item.cell_id == target)
    decision = next(item for item in result.decisions if item.action.cell_id == target)
    expected = (
        RootCauseCategory.UNKNOWN
        if scenario_name in {"missing_neighbor", "mobility"}
        else result.scenario.ground_truth
    )
    assert diagnosis.probable_root_cause is expected
    assert decision.action in result.recommendations
    assert decision.action.action_type is (
        ActionType.ACTIVATE_CAPACITY if scenario_name == "congestion" else ActionType.HUMAN_REVIEW
    )
    assert "No command" in decision.note
    assert result.training_seed != result.evaluation_seed
    assert result.evaluation_mode == "synthetic_replay"


def test_workflow_rejects_run_ending_before_fault(closed_loop: ClosedLoopEngine) -> None:
    with pytest.raises(ValueError, match="extend beyond"):
        closed_loop.run("congestion", steps=10)


def test_all_workflow_telemetry_is_labeled(closed_loop: ClosedLoopEngine) -> None:
    run = closed_loop.run("coverage")
    assert any(item.ground_truth is RootCauseCategory.COVERAGE for item in run.telemetry)
    assert any(item.ground_truth is RootCauseCategory.NORMAL for item in run.telemetry)


def test_replay_freshness_uses_latest_telemetry_not_anomaly_time(
    closed_loop: ClosedLoopEngine,
) -> None:
    run = closed_loop.run("congestion")
    target = run.scenario.target_cells[0]
    decision = next(item for item in run.decisions if item.action.cell_id == target)
    latest_timestamp = max(item.timestamp for item in run.telemetry)
    assert decision.guardrail.evaluated_at == latest_timestamp
    assert decision.guardrail.evaluated_at >= decision.action.proposed_at


def test_workflow_selection_does_not_filter_by_scenario_truth(
    closed_loop: ClosedLoopEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = closed_loop.config.scenario("outage")
    telemetry = closed_loop.generator.generate(2, seed=901)
    sample = next(item for item in telemetry if item.cell_id not in scenario.target_cells)
    anomaly = Anomaly(
        cell_id=sample.cell_id,
        timestamp=sample.timestamp,
        anomaly_type="threshold",
        score=1.0,
        evidence={"availability_pct": 0.0, "rrc_success_pct": 0.0},
        detector="test-double",
    )
    monkeypatch.setattr(closed_loop.generator, "generate", lambda *args, **kwargs: telemetry)
    monkeypatch.setattr(closed_loop.rules, "detect", lambda _: [anomaly])
    monkeypatch.setattr(closed_loop.ml, "detect", lambda _: [])

    result = closed_loop.run_scenario(scenario, steps=scenario.start_step + 1)

    assert [item.cell_id for item in result.diagnoses] == [sample.cell_id]


def test_workflow_is_deterministic_for_fixed_training_and_evaluation_seeds(
    project_config: ProjectConfig,
) -> None:
    first = ClosedLoopEngine(project_config, training_seed=17).run("bler", seed=211)
    second = ClosedLoopEngine(project_config, training_seed=17).run("bler", seed=211)
    assert first.telemetry == second.telemetry
    assert first.anomalies == second.anomalies
    assert first.diagnoses == second.diagnoses
    assert first.decisions == second.decisions
