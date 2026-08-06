import json
from pathlib import Path

from ai_ran_assurance.evaluation.benchmark import DISCLAIMER, run_and_write_benchmark


def test_benchmark_generates_real_machine_and_human_results(tmp_path: Path) -> None:
    artifact = tmp_path / "results.json"
    markdown = tmp_path / "results.md"
    results = run_and_write_benchmark(artifact, markdown)
    assert results["protocol"] == {
        "type": "closed-set synthetic stress test",
        "training_seed": 17,
        "evaluation_seeds": [101, 211, 307],
        "evaluation_severities": [0.55, 0.8],
        "fault_scenarios": 8,
        "truth_used_only_for_scoring": True,
    }
    assert results["scenario_run_count"] == 48
    assert 0 <= results["fault_episode_detection_rate"] <= 1
    assert results["root_cause"]["ambiguous_episodes"] > 0
    assert results["guardrail_regression"]["safe_control_approved"] == 1
    assert results["guardrail_regression"]["regression_pass_rate"] == 1.0
    assert results["runtime_observation"]["api_health_smoke"] == {
        "requests": 25,
        "all_successful": True,
        "timing_reported": False,
        "scope": "in-process API health smoke; no latency or load claim",
    }
    assert json.loads(artifact.read_text(encoding="utf-8"))["disclaimer"] == DISCLAIMER
    assert DISCLAIMER in markdown.read_text(encoding="utf-8")
    assert "not an external validation benchmark" in markdown.read_text(encoding="utf-8")
