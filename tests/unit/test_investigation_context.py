from datetime import timedelta

import pytest

from ai_ran_assurance.config import InvestigationSettings, ProjectConfig
from ai_ran_assurance.investigation import (
    InvestigationContextBuilder,
    InvestigationMode,
    default_retriever,
    select_anomaly,
)
from ai_ran_assurance.investigation.models import EvidenceKind
from ai_ran_assurance.workflow import ClosedLoopEngine, ScenarioRun


def _run(project_config: ProjectConfig) -> tuple[ClosedLoopEngine, ScenarioRun]:
    engine = ClosedLoopEngine(project_config, training_seed=17)
    return engine, engine.run("congestion", seed=101)


def test_context_contains_only_observable_bounded_data(project_config: ProjectConfig) -> None:
    engine, run = _run(project_config)
    anomaly = select_anomaly(run.anomalies)
    context = InvestigationContextBuilder(
        project_config.investigation,
        project_config.thresholds,
        default_retriever(),
    ).build(
        topology=run.topology,
        telemetry=run.telemetry,
        anomaly=anomaly,
    )
    dumped = context.model_dump(mode="json")
    forbidden = {
        "scenario",
        "fault_type",
        "target_cells",
        "start_step",
        "duration",
        "severity",
        "affected_kpis",
        "ground_truth",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    assert not forbidden & keys(dumped)
    assert context.metadata.evaluation_truth_excluded
    assert len(context.evidence) <= project_config.investigation.max_evidence_items
    assert len(context.retrieved_knowledge) <= project_config.investigation.retrieval_top_k
    assert all(item.timestamp <= context.analyzed_timestamp for item in context.evidence)
    primary_history = [
        item
        for item in context.evidence
        if item.kind is EvidenceKind.TELEMETRY and item.cell_id == context.analyzed_cell
    ]
    assert len(primary_history) <= project_config.investigation.context_lookback_samples
    assert [item.timestamp for item in primary_history] == sorted(
        item.timestamp for item in primary_history
    )
    assert engine.config.scenario("congestion").name not in dumped


def test_context_excludes_future_telemetry_and_is_deterministic(
    project_config: ProjectConfig,
) -> None:
    _, run = _run(project_config)
    anomaly = select_anomaly(run.anomalies)
    matching = next(
        item
        for item in run.telemetry
        if item.cell_id == anomaly.cell_id and item.timestamp == anomaly.timestamp
    )
    future = type(matching).model_validate(
        matching.model_dump()
        | {
            "timestamp": matching.timestamp + timedelta(hours=2),
            "step": matching.step + 100,
        }
    )
    builder = InvestigationContextBuilder(
        project_config.investigation,
        project_config.thresholds,
        default_retriever(),
    )
    first = builder.build(
        topology=run.topology,
        telemetry=[*run.telemetry, future],
        anomaly=anomaly,
    )
    second = builder.build(
        topology=run.topology,
        telemetry=list(reversed([*run.telemetry, future])),
        anomaly=anomaly,
    )
    assert first == second
    assert future.timestamp not in {item.timestamp for item in first.evidence}


def test_context_limits_and_modes_are_enforced(project_config: ProjectConfig) -> None:
    _, run = _run(project_config)
    anomaly = select_anomaly(run.anomalies)
    settings = InvestigationSettings.model_validate(
        project_config.investigation.model_dump()
        | {"context_lookback_samples": 2, "max_evidence_items": 3, "retrieval_top_k": 1}
    )
    builder = InvestigationContextBuilder(settings, project_config.thresholds, default_retriever())
    context = builder.build(
        topology=run.topology,
        telemetry=run.telemetry,
        anomaly=anomaly,
    )
    assert len(context.evidence) == 3
    assert len(context.retrieved_knowledge) <= 1
    diagnosis = next(item for item in run.diagnoses if item.cell_id == anomaly.cell_id)
    with pytest.raises(ValueError, match="independent mode"):
        builder.build(
            topology=run.topology,
            telemetry=run.telemetry,
            anomaly=anomaly,
            deterministic_candidate=diagnosis,
        )
    reviewed = builder.build(
        topology=run.topology,
        telemetry=run.telemetry,
        anomaly=anomaly,
        mode=InvestigationMode.REVIEW,
        deterministic_candidate=diagnosis,
    )
    assert reviewed.candidate_assessment is not None
    assert reviewed.candidate_assessment.category is diagnosis.probable_root_cause


def test_selection_uses_only_anomaly_properties(project_config: ProjectConfig) -> None:
    _, run = _run(project_config)
    selected = select_anomaly(run.anomalies)
    assert (
        selected
        == sorted(
            run.anomalies,
            key=lambda item: (-item.score, item.timestamp, item.cell_id, item.detector),
        )[0]
    )
    assert select_anomaly(run.anomalies, selected.cell_id).cell_id == selected.cell_id
    with pytest.raises(ValueError, match="no detected anomaly"):
        select_anomaly(run.anomalies, "CELL-020")
