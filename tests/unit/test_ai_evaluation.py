import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.evaluation.ai_benchmark import (
    context_contains_evaluation_truth,
    run_ai_benchmark,
)
from ai_ran_assurance.evaluation.ai_metrics import (
    ScoredInvestigation,
    classify_error,
    investigation_metrics,
)
from ai_ran_assurance.investigation import (
    FixtureProvider,
    InvestigationService,
    ProviderUnavailableError,
)
from ai_ran_assurance.workflow import ClosedLoopEngine


def test_truth_scanner_finds_nested_answer_keys() -> None:
    assert context_contains_evaluation_truth({"nested": [{"ground_truth": "outage"}]})
    assert context_contains_evaluation_truth({"scenario": "outage"})
    assert not context_contains_evaluation_truth(
        {"analyzed_cell": "CELL-012", "evidence": [{"availability_pct": 0}]}
    )


def test_ai_metrics_and_error_taxonomy(project_config: ProjectConfig) -> None:
    engine = ClosedLoopEngine(project_config, training_seed=17)
    service = InvestigationService(project_config, FixtureProvider())
    cases: list[ScoredInvestigation] = []
    for name, ambiguous in (("congestion", False), ("mobility", True)):
        run = engine.run(name, seed=101)
        report = service.investigate(
            topology=run.topology,
            telemetry=run.telemetry,
            anomalies=run.anomalies,
        )
        cases.append(
            ScoredInvestigation(
                expected=run.scenario.ground_truth,
                ambiguous=ambiguous,
                report=report,
            )
        )
    metrics = investigation_metrics(cases)
    assert metrics["case_count"] == 2
    assert metrics["top1_accuracy_nonambiguous_cases"] == 1.0
    assert metrics["ambiguity_respect_rate"] == 1.0
    assert metrics["evidence_reference_validity_rate"] == 1.0
    assert metrics["provider_failure_rate"] == 0.0
    assert metrics["schema_validation_failure_rate"] == 0.0
    assert [classify_error(case) for case in cases] == ["none", "none"]
    with pytest.raises(ValueError, match="at least one"):
        investigation_metrics([])


def test_offline_benchmark_keeps_truth_in_scorer_only(project_config: ProjectConfig) -> None:
    selected = [
        project_config.scenario("congestion"),
        project_config.scenario("missing_neighbor"),
    ]
    small = ProjectConfig.model_validate(project_config.model_dump() | {"scenarios": selected})
    results = run_ai_benchmark(config=small)
    assert results["evaluation_type"] == "deterministic_fixture_contract"
    assert results["protocol"]["truth_used_only_by_scorer"] is True
    assert results["metrics"]["case_count"] == 2
    assert results["metrics"]["core_decision_isolation_pass_rate"] == 1.0
    assert all(not item["context_has_evaluation_truth"] for item in results["records"])
    assert all(item["live_model"] is False for item in results["records"])
    assert all(item["latency_ms"] is None for item in results["records"])
    assert all(item["input_tokens"] is None for item in results["records"])


def test_live_evaluation_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_RAN_RUN_LIVE_EVAL", raising=False)
    with pytest.raises(ProviderUnavailableError, match="live AI evaluation disabled"):
        run_ai_benchmark(provider_name="openai")
