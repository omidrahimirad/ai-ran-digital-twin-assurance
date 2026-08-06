import pytest

from ai_ran_assurance.domain.enums import RootCauseCategory
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
    assert result.diagnoses[0].probable_root_cause is result.scenario.ground_truth
    assert result.recommendations[0] == result.decisions[0].action
    assert "No command" in result.decisions[0].note


def test_workflow_rejects_run_ending_before_fault(closed_loop: ClosedLoopEngine) -> None:
    with pytest.raises(ValueError, match="extend beyond"):
        closed_loop.run("congestion", steps=10)


def test_all_workflow_telemetry_is_labeled(closed_loop: ClosedLoopEngine) -> None:
    run = closed_loop.run("coverage")
    assert any(item.ground_truth is RootCauseCategory.COVERAGE for item in run.telemetry)
    assert any(item.ground_truth is RootCauseCategory.NORMAL for item in run.telemetry)
