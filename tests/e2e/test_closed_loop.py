from ai_ran_assurance.domain.enums import DecisionStatus
from ai_ran_assurance.workflow import ClosedLoopEngine


def test_complete_fault_to_shadow_report(closed_loop: ClosedLoopEngine) -> None:
    run = closed_loop.run("missing_neighbor")
    decision = run.decisions[0]
    assert run.diagnoses[0].probable_root_cause is run.scenario.ground_truth
    assert (
        decision.prediction.predicted_kpis["handover_success_pct"]
        > (decision.prediction.before_kpis["handover_success_pct"])
    )
    assert decision.status is DecisionStatus.SHADOW_APPROVED
    assert decision.note.endswith("real RAN.")
