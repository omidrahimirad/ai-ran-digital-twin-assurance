import json
from pathlib import Path

from ai_ran_assurance.evaluation.benchmark import DISCLAIMER, run_and_write_benchmark


def test_benchmark_generates_real_machine_and_human_results(tmp_path: Path) -> None:
    artifact = tmp_path / "results.json"
    markdown = tmp_path / "results.md"
    results = run_and_write_benchmark(artifact, markdown)
    assert results["scenario_count"] == 8
    assert results["root_cause_accuracy"] == 1.0
    assert results["unsafe_actions_rejected_pct"] == 100.0
    assert json.loads(artifact.read_text(encoding="utf-8"))["disclaimer"] == DISCLAIMER
    assert DISCLAIMER in markdown.read_text(encoding="utf-8")
