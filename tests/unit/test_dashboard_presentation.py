import json
from pathlib import Path
from typing import NoReturn

import pytest

from ai_ran_assurance.config import ProjectConfig
from ai_ran_assurance.domain.enums import DecisionStatus
from ai_ran_assurance.workflow import ClosedLoopEngine
from dashboard.presentation import (
    build_safe_control_case,
    guardrail_rows,
    kpi_figure,
    load_json_object,
    parse_api_health,
    probe_api_health,
    run_scenario,
    topology_figure,
)


@pytest.mark.parametrize(
    ("payload", "available", "label"),
    [
        (b'{"status":"ok","mode":"shadow","synthetic_data":true}', True, "Available"),
        (b"not-json", False, "Malformed response"),
        (b'{"status":"ok","mode":"live","synthetic_data":true}', False, "Unexpected mode"),
    ],
)
def test_parse_api_health_contract(payload: bytes, available: bool, label: str) -> None:
    status = parse_api_health(payload)
    assert status.available is available
    assert status.label == label


def test_probe_api_health_handles_unavailable_service() -> None:
    def unavailable(*_: object, **__: object) -> NoReturn:
        raise TimeoutError

    status = probe_api_health("http://127.0.0.1:65535", opener=unavailable)

    assert not status.available
    assert status.label == "Unavailable"
    assert "TimeoutError" in status.detail


def test_scenario_controls_use_validated_deterministic_variants(
    closed_loop: ClosedLoopEngine,
) -> None:
    first = run_scenario(closed_loop, "coverage", severity=0.55, seed=307)
    second = run_scenario(closed_loop, "coverage", severity=0.55, seed=307)

    assert first.scenario.severity == 0.55
    assert first.evaluation_seed == 307
    assert first.telemetry == second.telemetry
    assert first.anomalies == second.anomalies


def test_safe_control_uses_actual_guardrail_path(project_config: ProjectConfig) -> None:
    case = build_safe_control_case(ClosedLoopEngine(project_config, training_seed=17))

    assert case.decision.guardrail.approved
    assert not case.decision.guardrail.violations
    assert case.decision.status is DecisionStatus.SHADOW_APPROVED
    assert case.decision.action.diagnosis_confidence == 0.9
    assert case.decision.prediction.confidence == 0.9


def test_topology_and_guardrail_views_reflect_domain_objects(
    closed_loop: ClosedLoopEngine,
    project_config: ProjectConfig,
) -> None:
    run = closed_loop.run("congestion")
    figure = topology_figure(run)
    decision = run.decisions[0]
    rows = guardrail_rows(decision, project_config.thresholds)
    kpi_chart = kpi_figure(
        run,
        cell_id=run.scenario.target_cells[0],
        field="prb_utilization_pct",
        thresholds=project_config.thresholds,
        interval_minutes=project_config.network.interval_minutes,
    )

    assert figure.to_json() == topology_figure(run).to_json()
    assert {cell.cell_id for cell in run.topology.cells}.issubset(
        {str(label) for trace in figure.data for label in (trace.text or [])}
    )
    assert any(row["Guardrail"] == "Telemetry freshness" for row in rows)
    assert any(row["Status"] == "Fail" for row in rows)
    expected_values = [
        sample.prb_utilization_pct
        for sample in run.telemetry
        if sample.cell_id == run.scenario.target_cells[0]
    ]
    assert list(kpi_chart.data[0].y) == expected_values
    assert len(kpi_chart.layout.shapes) == 2  # Policy threshold plus evaluation-truth interval.


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("not-json", "JSONDecodeError"),
        (json.dumps([1, 2, 3]), "expected a JSON object"),
    ],
)
def test_load_json_object_reports_malformed_artifacts(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(content, encoding="utf-8")

    value, error = load_json_object(artifact)

    assert value is None
    assert error is not None
    assert expected in error
