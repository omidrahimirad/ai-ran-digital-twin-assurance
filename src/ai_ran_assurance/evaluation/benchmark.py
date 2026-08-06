import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ai_ran_assurance.api.main import app
from ai_ran_assurance.domain.enums import ActionType, RootCauseCategory
from ai_ran_assurance.domain.models import (
    CorrectiveAction,
    FaultScenario,
    TwinPrediction,
)
from ai_ran_assurance.evaluation.metrics import binary_metrics
from ai_ran_assurance.twin import NetworkTwin
from ai_ran_assurance.workflow import ClosedLoopEngine

DISCLAIMER = (
    "Reported results are based on closed-set synthetic RAN scenarios and do not "
    "represent performance on a commercial mobile network."
)
TRAINING_SEED = 17
EVALUATION_SEEDS = (101, 211, 307)
EVALUATION_SEVERITIES = (0.55, 0.8)


def _validated_copy(model: Any, **updates: Any) -> Any:
    values = model.model_dump()
    values.update(updates)
    return type(model).model_validate(values)


def _guardrail_regression(engine: ClosedLoopEngine) -> dict[str, int | float]:
    run = engine.run("congestion", seed=EVALUATION_SEEDS[0])
    target = run.scenario.target_cells[0]
    decision = next(item for item in run.decisions if item.action.cell_id == target)
    diagnosis = next(item for item in run.diagnoses if item.cell_id == target)
    action = _validated_copy(decision.action, diagnosis_confidence=0.9)
    prediction = _validated_copy(decision.prediction, confidence=0.9)
    sample = next(
        item
        for item in run.telemetry
        if item.cell_id == target and item.timestamp == diagnosis.timestamp
    )
    validator = engine.guardrails
    control = validator.validate(
        action,
        prediction,
        telemetry_timestamp=sample.timestamp,
        evaluated_at=sample.timestamp,
    )
    cases: list[
        tuple[
            CorrectiveAction,
            TwinPrediction,
            datetime,
            datetime,
            list[CorrectiveAction],
        ]
    ] = []
    for field, value in (
        ("handover_success_pct", 80.0),
        ("rrc_success_pct", 90.0),
        ("availability_pct", 98.0),
        ("latency_ms", 120.0),
        ("call_drop_pct", 5.0),
        ("bler_pct", 25.0),
    ):
        changed = prediction.predicted_kpis | {field: value}
        cases.append(
            (
                action,
                _validated_copy(prediction, predicted_kpis=changed),
                sample.timestamp,
                sample.timestamp,
                [],
            )
        )
    low_prediction = _validated_copy(prediction, confidence=0.2)
    cases.append((action, low_prediction, sample.timestamp, sample.timestamp, []))
    low_diagnosis = _validated_copy(action, diagnosis_confidence=0.2)
    cases.append((low_diagnosis, prediction, sample.timestamp, sample.timestamp, []))
    excessive_capacity = _validated_copy(
        action,
        parameters={"capacity_delta_pct": engine.config.thresholds.max_capacity_increase_pct + 1},
    )
    cases.append((excessive_capacity, prediction, sample.timestamp, sample.timestamp, []))
    cases.append(
        (
            action,
            prediction,
            sample.timestamp - timedelta(hours=1),
            sample.timestamp,
            [],
        )
    )
    cases.append(
        (
            action,
            prediction,
            sample.timestamp + timedelta(minutes=1),
            sample.timestamp,
            [],
        )
    )
    previous = _validated_copy(action, proposed_at=sample.timestamp - timedelta(minutes=1))
    cases.append((action, prediction, sample.timestamp, sample.timestamp, [previous]))
    mismatched_id = _validated_copy(prediction, action_id="different-action")
    cases.append((action, mismatched_id, sample.timestamp, sample.timestamp, []))
    mismatched_cell = _validated_copy(prediction, cell_id="CELL-020")
    cases.append((action, mismatched_cell, sample.timestamp, sample.timestamp, []))
    proposal_before_data = _validated_copy(
        action, proposed_at=sample.timestamp - timedelta(minutes=1)
    )
    cases.append((proposal_before_data, prediction, sample.timestamp, sample.timestamp, []))
    review = CorrectiveAction(
        action_id="human-review-regression",
        cell_id=target,
        action_type=ActionType.HUMAN_REVIEW,
        parameters={},
        diagnosis_confidence=0.9,
        rationale="Explicit guardrail regression case.",
        proposed_at=sample.timestamp,
    )
    review_prediction = engine.twin_simulator.simulate(
        NetworkTwin(
            run.topology,
            [item for item in run.telemetry if item.timestamp == sample.timestamp],
        ),
        review,
    )
    cases.append((review, review_prediction, sample.timestamp, sample.timestamp, []))
    rejected = sum(
        not validator.validate(
            candidate,
            candidate_prediction,
            telemetry_timestamp=telemetry_timestamp,
            evaluated_at=evaluated_at,
            action_history=history,
        ).approved
        for candidate, candidate_prediction, telemetry_timestamp, evaluated_at, history in cases
    )
    return {
        "safe_control_approved": int(control.approved),
        "unsafe_or_escalation_cases": len(cases),
        "cases_rejected_or_escalated": rejected,
        "regression_pass_rate": round(rejected / len(cases), 6),
    }


def _api_health_smoke() -> dict[str, bool | int | str]:
    successful = 0
    with TestClient(app) as client:
        for _ in range(25):
            response = client.get("/health")
            response.raise_for_status()
            successful += 1
    return {
        "requests": successful,
        "all_successful": successful == 25,
        "timing_reported": False,
        "scope": "in-process API health smoke; no latency or load claim",
    }


def _scenario_at_severity(scenario: FaultScenario, severity: float) -> FaultScenario:
    values = scenario.model_dump()
    values["severity"] = severity
    return FaultScenario.model_validate(values)


def run_benchmark() -> dict[str, Any]:
    """Evaluate holdout seeds and severities without using truth in the workflow."""
    engine = ClosedLoopEngine(training_seed=TRAINING_SEED)
    all_truth: list[bool] = []
    all_predicted: list[bool] = []
    detection_delays: list[float] = []
    episodes = 0
    detected_episodes = 0
    diagnosed_episodes = 0
    correct_causes = 0
    ambiguous_causes = 0
    scenario_results: dict[str, dict[str, int]] = {
        scenario.name: {
            "episodes": 0,
            "detected_episodes": 0,
            "diagnosed_episodes": 0,
            "correct_root_causes": 0,
            "ambiguous_root_causes": 0,
        }
        for scenario in engine.config.scenarios
    }
    for configured in engine.config.scenarios:
        for severity in EVALUATION_SEVERITIES:
            scenario = _scenario_at_severity(configured, severity)
            for seed in EVALUATION_SEEDS:
                run = engine.run_scenario(scenario, seed=seed)
                episodes += 1
                scenario_result = scenario_results[scenario.name]
                scenario_result["episodes"] += 1
                detected = {(item.cell_id, item.timestamp) for item in run.anomalies}
                truth = [
                    item.ground_truth is not RootCauseCategory.NORMAL for item in run.telemetry
                ]
                predicted = [(item.cell_id, item.timestamp) in detected for item in run.telemetry]
                all_truth.extend(truth)
                all_predicted.extend(predicted)
                target_cells = set(scenario.target_cells)
                target_detections = [
                    item
                    for item in run.anomalies
                    if item.cell_id in target_cells
                    and scenario.start_step
                    <= next(
                        sample.step
                        for sample in run.telemetry
                        if sample.cell_id == item.cell_id and sample.timestamp == item.timestamp
                    )
                    < scenario.start_step + scenario.duration
                ]
                if not target_detections:
                    continue
                detected_episodes += 1
                scenario_result["detected_episodes"] += 1
                start_timestamp = next(
                    item.timestamp
                    for item in run.telemetry
                    if item.step == scenario.start_step and item.cell_id == scenario.target_cells[0]
                )
                delay = (
                    min(item.timestamp for item in target_detections) - start_timestamp
                ).total_seconds() / 60
                detection_delays.append(delay)
                first_detection = min(target_detections, key=lambda item: item.timestamp)
                evidence_sample = next(
                    sample
                    for sample in run.telemetry
                    if sample.cell_id == first_detection.cell_id
                    and sample.timestamp == first_detection.timestamp
                )
                # Truth selects episode evidence for scoring only. RCA receives the
                # same anomaly and KPI sample as it does in the workflow.
                diagnosis = engine.rca.diagnose(first_detection, evidence_sample)
                diagnosed_episodes += 1
                scenario_result["diagnosed_episodes"] += 1
                if diagnosis.probable_root_cause is RootCauseCategory.UNKNOWN:
                    ambiguous_causes += 1
                    scenario_result["ambiguous_root_causes"] += 1
                if diagnosis.probable_root_cause is scenario.ground_truth:
                    correct_causes += 1
                    scenario_result["correct_root_causes"] += 1
    detection = binary_metrics(all_truth, all_predicted)
    return {
        "disclaimer": DISCLAIMER,
        "protocol": {
            "type": "closed-set synthetic stress test",
            "training_seed": TRAINING_SEED,
            "evaluation_seeds": list(EVALUATION_SEEDS),
            "evaluation_severities": list(EVALUATION_SEVERITIES),
            "fault_scenarios": len(engine.config.scenarios),
            "truth_used_only_for_scoring": True,
        },
        "scenario_run_count": episodes,
        "telemetry_sample_count": len(all_truth),
        "detection": detection.as_dict(),
        "fault_episode_detection_rate": round(detected_episodes / episodes, 6),
        "average_detection_delay_minutes_on_detected_episodes": (
            round(statistics.mean(detection_delays), 3) if detection_delays else None
        ),
        "root_cause": {
            "accuracy_on_diagnosed_episodes": (
                round(correct_causes / diagnosed_episodes, 6) if diagnosed_episodes else None
            ),
            "diagnosed_episodes": diagnosed_episodes,
            "correct_episodes": correct_causes,
            "ambiguous_episodes": ambiguous_causes,
        },
        "guardrail_regression": _guardrail_regression(engine),
        "runtime_observation": {"api_health_smoke": _api_health_smoke()},
        "scenarios": scenario_results,
    }


def _markdown(results: dict[str, Any]) -> str:
    detection = results["detection"]
    root_cause = results["root_cause"]
    guardrails = results["guardrail_regression"]
    api_smoke = results["runtime_observation"]["api_health_smoke"]
    protocol = results["protocol"]
    rows = "\n".join(
        f"| {name} | {item['episodes']} | {item['detected_episodes']} | "
        f"{item['correct_root_causes']} | {item['ambiguous_root_causes']} |"
        for name, item in results["scenarios"].items()
    )
    delay_text = results["average_detection_delay_minutes_on_detected_episodes"]
    rca_text = root_cause["accuracy_on_diagnosed_episodes"]
    guardrail_text = (
        f"{guardrails['cases_rejected_or_escalated']}/{guardrails['unsafe_or_escalation_cases']}"
    )
    return f"""# Hardened synthetic evaluation results

> **{results["disclaimer"]}**

This is a **{protocol["type"]}**, not an external validation benchmark. The model is
trained with seed `{protocol["training_seed"]}` and evaluated on seeds
`{protocol["evaluation_seeds"]}` at severities `{protocol["evaluation_severities"]}`.
Ground truth is used only by this evaluator for scoring, not by workflow selection.

## Results

| Metric | Result |
|---|---:|
| Scenario runs | {results["scenario_run_count"]} |
| Telemetry samples | {results["telemetry_sample_count"]} |
| Precision | {detection["precision"]:.4f} |
| Recall | {detection["recall"]:.4f} |
| F1-score | {detection["f1_score"]:.4f} |
| False-alarm rate | {detection["false_alarm_rate"]:.4f} |
| Fault-episode detection rate | {results["fault_episode_detection_rate"]:.2%} |
| Mean delay on detected episodes | {delay_text} minutes |
| RCA accuracy on diagnosed episodes | {rca_text} |
| Ambiguous RCA episodes | {root_cause["ambiguous_episodes"]} |
| Guardrail regression cases rejected/escalated | {guardrail_text} |
| Safe guardrail control approved | {guardrails["safe_control_approved"]} |
| API health smoke | {api_smoke["requests"]}/25 successful |

No API latency number is reported: an in-process test client cannot establish service,
network, concurrency, or scalability performance.

## Scenario episodes

| Scenario | Runs | Detected | Correct RCA | Ambiguous RCA |
|---|---:|---:|---:|---:|
{rows}

Missed episodes remain false negatives. RCA accuracy is reported only where a target
episode was both detected and diagnosed; ambiguity is retained rather than forced into a
specific mobility cause. No result establishes RF accuracy, causal validity, standards
conformance, or performance on external telemetry.
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
