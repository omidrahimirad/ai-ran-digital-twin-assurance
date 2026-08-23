"""Leakage-safe evaluation harness for the optional AI investigation layer."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from ai_ran_assurance import __version__
from ai_ran_assurance.config import ProjectConfig, load_config
from ai_ran_assurance.domain.models import FaultScenario
from ai_ran_assurance.evaluation.ai_metrics import (
    ScoredInvestigation,
    classify_error,
    investigation_metrics,
)
from ai_ran_assurance.investigation import (
    InvestigationService,
    ProviderUnavailableError,
    provider_from_name,
)
from ai_ran_assurance.workflow import ClosedLoopEngine, ScenarioRun

AI_TRAINING_SEED = 17
AI_SMOKE_SEEDS = (101,)
AI_FULL_SEEDS = (101, 211, 307)
AI_SMOKE_SEVERITIES = (0.8,)
AI_FULL_SEVERITIES = (0.55, 0.8)
AMBIGUOUS_SCENARIOS = frozenset({"missing_neighbor", "mobility"})
FORBIDDEN_CONTEXT_KEYS = frozenset(
    {
        "scenario",
        "scenario_name",
        "fault_type",
        "target_cells",
        "start_step",
        "duration",
        "severity",
        "affected_kpis",
        "ground_truth",
        "label",
    }
)


def _validated_scenario(scenario: FaultScenario, severity: float) -> FaultScenario:
    values = scenario.model_dump()
    values["severity"] = severity
    return FaultScenario.model_validate(values)


def _core_outputs(run: ScenarioRun) -> dict[str, Any]:
    return {
        "anomalies": [item.model_dump(mode="json") for item in run.anomalies],
        "diagnoses": [item.model_dump(mode="json") for item in run.diagnoses],
        "recommendations": [item.model_dump(mode="json") for item in run.recommendations],
        "decisions": [item.model_dump(mode="json") for item in run.decisions],
    }


def context_contains_evaluation_truth(value: Any) -> bool:
    if isinstance(value, dict):
        if FORBIDDEN_CONTEXT_KEYS & set(value):
            return True
        return any(context_contains_evaluation_truth(item) for item in value.values())
    if isinstance(value, list):
        return any(context_contains_evaluation_truth(item) for item in value)
    return False


def _record(
    *,
    scenario: FaultScenario,
    evaluation_seed: int,
    report: Any,
    core_isolated: bool,
) -> dict[str, Any]:
    investigation = report.investigation
    provider_metadata = investigation.provider if investigation is not None else None
    return {
        "scenario_identifier_evaluator_only": scenario.name,
        "ground_truth_evaluator_only": scenario.ground_truth.value,
        "ambiguous_evidence_case": scenario.name in AMBIGUOUS_SCENARIOS,
        "severity_evaluator_only": scenario.severity,
        "training_seed": AI_TRAINING_SEED,
        "evaluation_seed": evaluation_seed,
        "analyzed_cell": report.context.analyzed_cell,
        "analyzed_timestamp": report.context.analyzed_timestamp.isoformat(),
        "provider": investigation.provider.provider if investigation else None,
        "model": investigation.provider.model if investigation else None,
        "live_model": investigation.provider.live_model if investigation else None,
        "temperature": provider_metadata.temperature if provider_metadata else None,
        "latency_ms": provider_metadata.latency_ms if provider_metadata else None,
        "input_tokens": provider_metadata.input_tokens if provider_metadata else None,
        "output_tokens": provider_metadata.output_tokens if provider_metadata else None,
        "prompt_version": report.context.metadata.prompt_version,
        "retrieval_top_k": report.context.metadata.retrieval_limit,
        "context_lookback_samples": report.context.metadata.lookback_samples,
        "context_has_evaluation_truth": context_contains_evaluation_truth(
            report.context.model_dump(mode="json")
        ),
        "predicted_root_cause": (
            investigation.output.primary_hypothesis.value if investigation else None
        ),
        "abstained": investigation.output.abstained if investigation else None,
        "verification_status": report.verification.status.value,
        "invalid_evidence_references": len(report.verification.invalid_evidence_references),
        "invalid_knowledge_citations": len(report.verification.invalid_knowledge_citations),
        "unsafe_action_violations": len(report.verification.safety_policy_violations),
        "core_decision_isolation_passed": core_isolated,
        "provider_failure": report.failure_reason,
        "failure_kind": report.failure_kind.value if report.failure_kind else None,
    }


def run_ai_benchmark(
    *,
    provider_name: str = "fixture",
    profile: Literal["smoke", "full"] = "smoke",
    config: ProjectConfig | None = None,
) -> dict[str, Any]:
    project = config or load_config()
    if provider_name != "fixture" and os.getenv("AI_RAN_RUN_LIVE_EVAL") != "1":
        raise ProviderUnavailableError(
            "live AI evaluation disabled; set AI_RAN_RUN_LIVE_EVAL=1 explicitly"
        )
    provider = provider_from_name(provider_name, project)
    service = InvestigationService(project, provider)
    engine = ClosedLoopEngine(project, training_seed=AI_TRAINING_SEED)
    seeds = AI_SMOKE_SEEDS if profile == "smoke" else AI_FULL_SEEDS
    severities = AI_SMOKE_SEVERITIES if profile == "smoke" else AI_FULL_SEVERITIES
    scored: list[ScoredInvestigation] = []
    records: list[dict[str, Any]] = []
    for base_scenario in project.scenarios:
        for severity in severities:
            scenario = _validated_scenario(base_scenario, severity)
            for evaluation_seed in seeds:
                core_only = engine.run_scenario(scenario, seed=evaluation_seed)
                with_advisory = engine.run_scenario(scenario, seed=evaluation_seed)
                before = _core_outputs(with_advisory)
                report = service.investigate(
                    topology=with_advisory.topology,
                    telemetry=with_advisory.telemetry,
                    anomalies=with_advisory.anomalies,
                )
                core_isolated = before == _core_outputs(with_advisory) == _core_outputs(core_only)
                if context_contains_evaluation_truth(report.context.model_dump(mode="json")):
                    raise AssertionError("evaluation truth leaked into investigation context")
                case = ScoredInvestigation(
                    expected=scenario.ground_truth,
                    ambiguous=scenario.name in AMBIGUOUS_SCENARIOS,
                    report=report,
                )
                scored.append(case)
                record = _record(
                    scenario=scenario,
                    evaluation_seed=evaluation_seed,
                    report=report,
                    core_isolated=core_isolated,
                )
                record["error_category"] = classify_error(case)
                records.append(record)
    metrics = investigation_metrics(scored)
    metrics["core_decision_isolation_pass_rate"] = round(
        sum(item["core_decision_isolation_passed"] for item in records) / len(records),
        6,
    )
    error_counts = Counter(item["error_category"] for item in records)
    return {
        "disclaimer": (
            "Offline fixture results verify pipeline contracts and are not LLM performance. "
            "No live-model result is reported unless explicitly run and identified."
        ),
        "evaluation_type": (
            "deterministic_fixture_contract"
            if provider_name == "fixture"
            else "explicit_live_model_evaluation"
        ),
        "profile": profile,
        "project_version": __version__,
        "provider": provider.metadata.model_dump(mode="json"),
        "protocol": {
            "training_seed": AI_TRAINING_SEED,
            "evaluation_seeds": list(seeds),
            "evaluation_severities": list(severities),
            "scenario_count": len(project.scenarios),
            "truth_used_only_by_scorer": True,
            "operational_anomaly_selection_without_truth": True,
            "prompt_version": "telecom-investigator-v1",
            "retrieval_top_k": project.investigation.retrieval_top_k,
            "context_lookback_samples": project.investigation.context_lookback_samples,
        },
        "metrics": metrics,
        "error_taxonomy_counts": dict(sorted(error_counts.items())),
        "records": records,
    }


def _artifact_readme(results: dict[str, Any]) -> str:
    metrics = results["metrics"]
    return f"""# Offline investigation-pipeline evaluation

> {results["disclaimer"]}

This small artifact is generated by the `{results["profile"]}` profile with provider type
`{results["evaluation_type"]}`. It tests context isolation, retrieval/citation integrity,
structured contracts, deterministic verification, ambiguity handling, and isolation from the
existing action path.

| Contract metric | Result |
|---|---:|
| Cases | {metrics["case_count"]} |
| Completed fixture investigations | {metrics["completed_investigations"]} |
| Non-ambiguous top-1 fixture agreement | {metrics["top1_accuracy_nonambiguous_cases"]:.2%} |
| Ambiguity-respect rate | {metrics["ambiguity_respect_rate"]:.2%} |
| Evidence-reference validity | {metrics["evidence_reference_validity_rate"]:.2%} |
| Knowledge-citation validity | {metrics["knowledge_citation_validity_rate"]:.2%} |
| Verifier rejection rate | {metrics["verifier_rejection_rate"]:.2%} |
| Provider failure rate | {metrics["provider_failure_rate"]:.2%} |
| Schema-validation failure rate | {metrics["schema_validation_failure_rate"]:.2%} |
| Core-decision isolation pass rate | {metrics["core_decision_isolation_pass_rate"]:.2%} |

These values describe a deterministic fixture, not model intelligence. Live-model evaluation
requires explicit provider configuration and is not part of the repository baseline.
"""


def run_and_write_ai_benchmark(
    *,
    provider_name: str = "fixture",
    profile: Literal["smoke", "full"] = "smoke",
    output_dir: str | Path = "reports/ai_evaluation",
) -> dict[str, Any]:
    results = run_ai_benchmark(provider_name=provider_name, profile=profile)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "summary.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "README.md").write_text(_artifact_readme(results), encoding="utf-8")
    fieldnames = list(results["records"][0]) if results["records"] else []
    with (destination / "error_analysis.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results["records"])
    return results
