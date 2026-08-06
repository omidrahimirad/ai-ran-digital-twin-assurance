from ai_ran_assurance.domain.enums import (
    ActionType,
    DecisionStatus,
    RootCauseCategory,
)
from ai_ran_assurance.workflow import ClosedLoopEngine


def test_complete_fault_to_shadow_report(closed_loop: ClosedLoopEngine) -> None:
    run = closed_loop.run("missing_neighbor")
    target = run.scenario.target_cells[0]
    diagnosis = next(item for item in run.diagnoses if item.cell_id == target)
    decision = next(item for item in run.decisions if item.action.cell_id == target)

    # KPIs alone cannot distinguish a missing relation from other mobility faults.
    assert diagnosis.probable_root_cause is RootCauseCategory.UNKNOWN
    assert diagnosis.confidence < closed_loop.config.thresholds.diagnosis_confidence_min
    assert decision.action.action_type is ActionType.HUMAN_REVIEW
    assert decision.prediction.before_kpis == decision.prediction.predicted_kpis
    assert decision.status is DecisionStatus.HUMAN_REVIEW
    assert any("human review" in item for item in decision.guardrail.violations)
    assert decision.note == "Shadow report only. No command was or can be sent to a real RAN."
