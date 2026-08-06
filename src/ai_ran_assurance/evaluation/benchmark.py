import json
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ai_ran_assurance.api.main import app
from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.domain.models import CorrectiveAction, TwinPrediction
from ai_ran_assurance.evaluation.metrics import binary_metrics
from ai_ran_assurance.workflow import ClosedLoopEngine

DISCLAIMER = (
    "Reported results are based on deterministic synthetic RAN scenarios and do not "
    "represent performance on a commercial mobile network."
)


def _coverage_percent(path: Path) -> float | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("totals", {}).get("percent_covered")
    return round(float(value), 2) if value is not None else None


def _unsafe_rejection_rate(engine: ClosedLoopEngine) -> tuple[float, int]:
    run = engine.run("congestion")
    decision = run.decisions[0]
    action = decision.action
    prediction = decision.prediction
    sample = next(
        item
        for item in run.telemetry
        if item.cell_id == action.cell_id and item.timestamp == run.diagnoses[0].timestamp
    )
    unsafe_predictions = []
    for field, value in (
        ("handover_success_pct", 80.0),
        ("rrc_success_pct", 90.0),
        ("availability_pct", prediction.before_kpis["availability_pct"] - 2),
        ("latency_ms", 120.0),
    ):
        changed = prediction.predicted_kpis.copy()
        changed[field] = value
        unsafe_predictions.append(prediction.model_copy(update={"predicted_kpis": changed}))
    unsafe_predictions.append(prediction.model_copy(update={"confidence": 0.2}))
    unsafe_actions: list[
        tuple[CorrectiveAction, TwinPrediction, datetime, datetime, list[CorrectiveAction]]
    ] = [(action, item, sample.timestamp, sample.timestamp, []) for item in unsafe_predictions]
    excessive_delta = action.model_copy(
        update={"parameters": {"parameter_delta": engine.config.thresholds.max_parameter_delta + 1}}
    )
    unsafe_actions.append((excessive_delta, prediction, sample.timestamp, sample.timestamp, []))
    unsafe_actions.append(
        (
            action,
            prediction,
            sample.timestamp - timedelta(hours=1),
            sample.timestamp,
            [],
        )
    )
    previous = action.model_copy(update={"proposed_at": sample.timestamp - timedelta(minutes=1)})
    unsafe_actions.append((action, prediction, sample.timestamp, sample.timestamp, [previous]))
    rejected = 0
    for (
        candidate,
        candidate_prediction,
        telemetry_timestamp,
        evaluated_at,
        history,
    ) in unsafe_actions:
        result = engine.guardrails.validate(
            candidate,
            candidate_prediction,
            telemetry_timestamp=telemetry_timestamp,
            evaluated_at=evaluated_at,
            action_history=history,
        )
        rejected += int(not result.approved)
    return round(100 * rejected / len(unsafe_actions), 2), len(unsafe_actions)


def _api_latency_ms() -> tuple[float, float]:
    samples: list[float] = []
    with TestClient(app) as client:
        for _ in range(25):
            started = time.perf_counter()
            response = client.get("/health")
            response.raise_for_status()
            samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return round(statistics.mean(samples), 3), round(ordered[p95_index], 3)


def run_benchmark() -> dict[str, Any]:
    """Evaluate fixed scenarios without tuning against this benchmark output."""
    engine = ClosedLoopEngine()
    all_truth: list[bool] = []
    all_predicted: list[bool] = []
    delays: list[float] = []
    correct_causes = 0
    scenario_results: dict[str, dict[str, Any]] = {}
    for scenario in engine.config.scenarios:
        run = engine.run(scenario.name)
        detected = {(item.cell_id, item.timestamp) for item in run.anomalies}
        truth = [item.ground_truth is not RootCauseCategory.NORMAL for item in run.telemetry]
        predicted = [(item.cell_id, item.timestamp) in detected for item in run.telemetry]
        all_truth.extend(truth)
        all_predicted.extend(predicted)
        target_detections = [
            item
            for item in run.anomalies
            if item.cell_id in scenario.target_cells
            and item.timestamp
            >= run.telemetry[scenario.start_step * len(run.topology.cells)].timestamp
        ]
        start_timestamp = run.telemetry[scenario.start_step * len(run.topology.cells)].timestamp
        delay = (
            min(item.timestamp for item in target_detections) - start_timestamp
        ).total_seconds() / 60
        delays.append(delay)
        diagnosed = run.diagnoses[0].probable_root_cause
        correct = diagnosed is scenario.ground_truth
        correct_causes += int(correct)
        scenario_results[scenario.name] = {
            "ground_truth": scenario.ground_truth.value,
            "diagnosed": diagnosed.value,
            "root_cause_correct": correct,
            "detection_delay_minutes": delay,
            "shadow_status": run.decisions[0].status.value,
        }
    detection = binary_metrics(all_truth, all_predicted)
    unsafe_rate, unsafe_cases = _unsafe_rejection_rate(engine)
    mean_latency, p95_latency = _api_latency_ms()
    return {
        "disclaimer": DISCLAIMER,
        "benchmark_seed": engine.config.network.seed,
        "scenario_count": len(engine.config.scenarios),
        "telemetry_sample_count": len(all_truth),
        "detection": detection.as_dict(),
        "average_detection_delay_minutes": round(statistics.mean(delays), 3),
        "root_cause_accuracy": round(correct_causes / len(engine.config.scenarios), 6),
        "unsafe_actions_rejected_pct": unsafe_rate,
        "unsafe_action_cases": unsafe_cases,
        "api_latency_ms": {"mean": mean_latency, "p95": p95_latency, "samples": 25},
        "test_coverage_pct": _coverage_percent(Path("artifacts/coverage.json")),
        "scenarios": scenario_results,
    }


def _markdown(results: dict[str, Any]) -> str:
    detection = results["detection"]
    latency = results["api_latency_ms"]
    rows = "\n".join(
        f"| {name} | {item['ground_truth']} | {item['diagnosed']} | "
        f"{item['detection_delay_minutes']:.1f} | {item['shadow_status']} |"
        for name, item in results["scenarios"].items()
    )
    coverage = (
        f"{results['test_coverage_pct']:.2f}%"
        if results["test_coverage_pct"] is not None
        else "not available (run coverage before benchmark)"
    )
    unsafe_summary = (
        f"{results['unsafe_actions_rejected_pct']:.2f}% ({results['unsafe_action_cases']} cases)"
    )
    api_summary = (
        f"{latency['mean']:.3f} ms mean / {latency['p95']:.3f} ms p95 ({latency['samples']} calls)"
    )
    return f"""# Reproducible benchmark results

> **{results["disclaimer"]}**

Generated by `python scripts/run_benchmark.py` with seed `{results["benchmark_seed"]}`.
No metric in this document is an invented or commercial-network benchmark.

## Summary

| Metric | Result |
|---|---:|
| Precision | {detection["precision"]:.4f} |
| Recall | {detection["recall"]:.4f} |
| F1-score | {detection["f1_score"]:.4f} |
| False-alarm rate | {detection["false_alarm_rate"]:.4f} |
| Average detection delay | {results["average_detection_delay_minutes"]:.3f} minutes |
| Root-cause accuracy | {results["root_cause_accuracy"]:.2%} |
| Unsafe candidate actions rejected | {unsafe_summary} |
| API `/health` latency | {api_summary} |
| Core-package test coverage | {coverage} |

## Scenario detail

| Scenario | Ground truth | Diagnosed | Delay (min) | Shadow decision |
|---|---|---|---:|---|
{rows}

The benchmark uses a deterministic synthetic engineering abstraction. It is not an
RF-accurate simulator, standards-conformance test, or evidence of production behavior.
"""


def run_and_write_benchmark(
    artifact_path: str | Path = "artifacts/sample_results.json",
    markdown_path: str | Path = "docs/results.md",
) -> dict[str, Any]:
    results = run_benchmark()
    artifact = Path(artifact_path)
    markdown = Path(markdown_path)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(_markdown(results), encoding="utf-8")
    return results
