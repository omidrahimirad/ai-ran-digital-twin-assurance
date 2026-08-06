"""Pure presentation helpers for the Streamlit dashboard.

The functions in this module adapt existing domain objects for display. They do not
change detector, diagnosis, response-surrogate, or guardrail behavior.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin
from urllib.request import urlopen

import networkx as nx
import plotly.graph_objects as go  # type: ignore[import-untyped]

from ai_ran_assurance.config import ThresholdSettings
from ai_ran_assurance.domain.enums import ActionType, AnomalyType, DecisionStatus
from ai_ran_assurance.domain.models import (
    Anomaly,
    CorrectiveAction,
    FaultScenario,
    ShadowDecision,
    TwinPrediction,
)
from ai_ran_assurance.twin import shadow_decision
from ai_ran_assurance.workflow import ClosedLoopEngine, ScenarioRun


@dataclass(frozen=True)
class KPIMetadata:
    label: str
    short_label: str
    unit: str
    decimals: int
    group: str
    threshold_field: str | None
    threshold_kind: Literal["minimum", "maximum"] | None


KPI_METADATA: dict[str, KPIMetadata] = {
    "prb_utilization_pct": KPIMetadata(
        "Physical resource block utilization",
        "PRB utilization",
        "%",
        1,
        "Capacity and load",
        "prb_utilization_max_pct",
        "maximum",
    ),
    "throughput_mbps": KPIMetadata(
        "Cell throughput",
        "Throughput",
        "Mbit/s",
        1,
        "Capacity and load",
        "throughput_min_mbps",
        "minimum",
    ),
    "latency_ms": KPIMetadata(
        "Modeled service latency",
        "Latency",
        "ms",
        1,
        "Capacity and load",
        "latency_max_ms",
        "maximum",
    ),
    "rsrp_dbm": KPIMetadata(
        "Reference signal received power",
        "RSRP",
        "dBm",
        1,
        "Radio quality",
        "rsrp_min_dbm",
        "minimum",
    ),
    "sinr_db": KPIMetadata(
        "Signal-to-interference-plus-noise ratio",
        "SINR",
        "dB",
        1,
        "Radio quality",
        "sinr_min_db",
        "minimum",
    ),
    "bler_pct": KPIMetadata(
        "Block error rate",
        "BLER",
        "%",
        2,
        "Radio quality",
        "bler_max_pct",
        "maximum",
    ),
    "rrc_success_pct": KPIMetadata(
        "Radio resource control setup success",
        "RRC setup success",
        "%",
        2,
        "Access and mobility",
        "rrc_success_min_pct",
        "minimum",
    ),
    "handover_success_pct": KPIMetadata(
        "Handover success",
        "Handover success",
        "%",
        2,
        "Access and mobility",
        "handover_success_min_pct",
        "minimum",
    ),
    "call_drop_pct": KPIMetadata(
        "Call-drop rate",
        "Call-drop rate",
        "%",
        2,
        "Access and mobility",
        "call_drop_max_pct",
        "maximum",
    ),
    "availability_pct": KPIMetadata(
        "Service availability",
        "Availability",
        "%",
        3,
        "Service availability",
        "availability_min_pct",
        "minimum",
    ),
}

KPI_GROUPS: dict[str, list[str]] = {
    group: [field for field, metadata in KPI_METADATA.items() if metadata.group == group]
    for group in (
        "Capacity and load",
        "Radio quality",
        "Access and mobility",
        "Service availability",
    )
}

SCENARIO_DESCRIPTIONS = {
    "congestion": "Resource pressure with queue growth and access degradation.",
    "interference": "Radio-quality degradation with SINR, BLER, and drop effects.",
    "missing_neighbor": (
        "Mobility degradation whose aggregate KPIs do not prove a missing relation."
    ),
    "outage": "Compound service, access, mobility, and throughput degradation.",
    "transport_latency": "Delay growth without the radio-load signature of congestion.",
    "coverage": "Signal-level degradation with radio-quality and access effects.",
    "bler": "Block-error increase with bounded throughput and drop effects.",
    "mobility": "Mobility degradation intentionally ambiguous at aggregate-KPI level.",
}


@dataclass(frozen=True)
class APIStatus:
    available: bool
    label: str
    detail: str


@dataclass(frozen=True)
class SafeControlCase:
    run: ScenarioRun
    decision: ShadowDecision


def parse_api_health(payload: bytes) -> APIStatus:
    """Validate the small API health contract without trusting arbitrary response data."""
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return APIStatus(False, "Malformed response", "The API health body is not valid JSON.")
    if not isinstance(decoded, dict):
        return APIStatus(False, "Malformed response", "The API health body is not an object.")
    expected = decoded.get("status") == "ok" and decoded.get("synthetic_data") is True
    if not expected:
        return APIStatus(
            False,
            "Unexpected response",
            "The endpoint did not confirm synthetic shadow-mode health.",
        )
    mode = decoded.get("mode")
    if mode != "shadow":
        return APIStatus(False, "Unexpected mode", f"The API reported mode {mode!r}.")
    return APIStatus(True, "Available", "Synthetic shadow-mode API health contract verified.")


def probe_api_health(
    base_url: str,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout_seconds: float = 0.8,
) -> APIStatus:
    """Return a display-safe API status; network failures never crash the dashboard."""
    try:
        with opener(
            urljoin(base_url.rstrip("/") + "/", "health"), timeout=timeout_seconds
        ) as response:
            payload = response.read()
    except (OSError, TimeoutError, ValueError) as exc:
        return APIStatus(False, "Unavailable", f"Health check failed: {type(exc).__name__}.")
    return parse_api_health(payload)


def load_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Load a committed JSON object with a concise error suitable for the UI."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"Cannot read {path.name}: {type(exc).__name__}."
    if not isinstance(value, dict):
        return None, f"Cannot read {path.name}: expected a JSON object."
    return value, None


def scenario_variant(configured: FaultScenario, severity: float) -> FaultScenario:
    """Build a validated severity variant without changing packaged configuration."""
    values = configured.model_dump()
    values["severity"] = severity
    return FaultScenario.model_validate(values)


def run_scenario(
    engine: ClosedLoopEngine,
    scenario_name: str,
    *,
    severity: float,
    seed: int,
) -> ScenarioRun:
    configured = engine.config.scenario(scenario_name)
    return engine.run_scenario(scenario_variant(configured, severity), seed=seed)


def build_safe_control_case(engine: ClosedLoopEngine) -> SafeControlCase:
    """Reproduce the benchmark's fresh, high-confidence guardrail control path."""
    run = engine.run("congestion", seed=101)
    target = run.scenario.target_cells[0]
    source_decision = next(item for item in run.decisions if item.action.cell_id == target)
    diagnosis = next(item for item in run.diagnoses if item.cell_id == target)
    action_values = source_decision.action.model_dump()
    action_values["diagnosis_confidence"] = 0.9
    action = CorrectiveAction.model_validate(action_values)
    prediction_values = source_decision.prediction.model_dump()
    prediction_values["confidence"] = 0.9
    prediction = TwinPrediction.model_validate(prediction_values)
    sample = next(
        item
        for item in run.telemetry
        if item.cell_id == target and item.timestamp == diagnosis.timestamp
    )
    result = engine.guardrails.validate(
        action,
        prediction,
        telemetry_timestamp=sample.timestamp,
        evaluated_at=sample.timestamp,
    )
    return SafeControlCase(run=run, decision=shadow_decision(action, prediction, result))


def detector_source(anomaly: Anomaly) -> str:
    if anomaly.anomaly_type is AnomalyType.THRESHOLD:
        return "Rule threshold"
    if anomaly.anomaly_type is AnomalyType.STATISTICAL:
        return "Rolling statistic + Isolation Forest (fused)"
    return "Isolation Forest"


def humanize_identifier(value: str) -> str:
    return value.replace("_", " ").strip().capitalize()


def format_kpi(field: str, value: float) -> str:
    metadata = KPI_METADATA[field]
    suffix = f" {metadata.unit}" if metadata.unit else ""
    return f"{value:.{metadata.decimals}f}{suffix}"


def topology_figure(run: ScenarioRun) -> go.Figure:
    """Render actual configured relations with deterministic non-geographic positions."""
    graph: nx.DiGraph[str] = nx.DiGraph()
    graph.add_nodes_from(cell.cell_id for cell in run.topology.cells)
    graph.add_edges_from(
        (relation.source_cell, relation.target_cell)
        for relation in run.topology.neighbor_relations
        if relation.enabled
    )
    positions = nx.circular_layout(graph, scale=1.0)
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for source, target in graph.edges:
        edge_x.extend([float(positions[source][0]), float(positions[target][0]), None])
        edge_y.extend([float(positions[source][1]), float(positions[target][1]), None])

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line={"color": "#CBD5E1", "width": 1},
            hoverinfo="skip",
            showlegend=False,
        )
    )

    anomalous = {item.cell_id for item in run.anomalies}
    impacted = {
        cell_id for decision in run.decisions for cell_id in decision.prediction.impacted_cell_kpis
    }
    affected = set(run.scenario.target_cells)
    styles = {
        "Normal": ("#4B6478", "circle"),
        "Detected anomaly": ("#C2413B", "circle"),
        "Impacted by response": ("#6D5BD0", "diamond"),
    }
    categories: dict[str, list[str]] = {label: [] for label in styles}
    for cell_id in graph.nodes:
        if cell_id in impacted:
            categories["Impacted by response"].append(cell_id)
        elif cell_id in anomalous:
            categories["Detected anomaly"].append(cell_id)
        else:
            categories["Normal"].append(cell_id)

    for label, (color, symbol) in styles.items():
        cells = categories[label]
        figure.add_trace(
            go.Scatter(
                x=[float(positions[cell][0]) for cell in cells],
                y=[float(positions[cell][1]) for cell in cells],
                mode="markers+text",
                text=cells,
                textposition="top center",
                textfont={"size": 10, "color": "#25364A"},
                marker={
                    "size": 13,
                    "color": color,
                    "symbol": symbol,
                    "line": {"color": "#FFFFFF", "width": 1.5},
                },
                name=label,
                customdata=[
                    ", ".join(
                        item
                        for item, active in (
                            ("detected anomaly", cell in anomalous),
                            ("evaluation target", cell in affected),
                            ("response-impacted", cell in impacted),
                        )
                        if active
                    )
                    or "normal"
                    for cell in cells
                ],
                hovertemplate="%{text}<br>%{customdata}<extra></extra>",
            )
        )

    affected_cells = [cell for cell in graph.nodes if cell in affected]
    figure.add_trace(
        go.Scatter(
            x=[float(positions[cell][0]) for cell in affected_cells],
            y=[float(positions[cell][1]) for cell in affected_cells],
            mode="markers",
            marker={
                "size": 24,
                "color": "rgba(0,0,0,0)",
                "symbol": "circle",
                "line": {"color": "#D28A25", "width": 3},
            },
            name="Evaluation target",
            text=affected_cells,
            hovertemplate="%{text}<br>evaluation target<extra></extra>",
        )
    )
    figure.update_layout(
        height=410,
        margin={"l": 8, "r": 8, "t": 15, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 11},
        },
        xaxis={"visible": False, "range": [-1.25, 1.25], "fixedrange": True},
        yaxis={
            "visible": False,
            "range": [-1.2, 1.2],
            "fixedrange": True,
            "scaleanchor": "x",
            "scaleratio": 1,
        },
        hoverlabel={"font_size": 12},
    )
    return figure


def kpi_figure(
    run: ScenarioRun,
    *,
    cell_id: str,
    field: str,
    thresholds: ThresholdSettings,
    interval_minutes: int,
) -> go.Figure:
    metadata = KPI_METADATA[field]
    samples = [item for item in run.telemetry if item.cell_id == cell_id]
    timestamps = [item.timestamp for item in samples]
    values = [float(getattr(item, field)) for item in samples]
    figure = go.Figure(
        go.Scatter(
            x=timestamps,
            y=values,
            mode="lines",
            line={"color": "#245B78", "width": 2},
            name=metadata.short_label,
            hovertemplate=(
                "%{x|%Y-%m-%d %H:%M UTC}<br>"
                + f"{metadata.short_label}: %{{y:.{metadata.decimals}f}} {metadata.unit}"
                + "<extra></extra>"
            ),
        )
    )
    if metadata.threshold_field is not None:
        threshold = float(getattr(thresholds, metadata.threshold_field))
        figure.add_hline(
            y=threshold,
            line={"color": "#7A4850", "dash": "dash", "width": 1.5},
            annotation_text=f"Policy {metadata.threshold_kind}: {format_kpi(field, threshold)}",
            annotation_position="top right",
        )
    active_samples = [
        item
        for item in samples
        if cell_id in run.scenario.target_cells
        and run.scenario.start_step <= item.step < run.scenario.start_step + run.scenario.duration
    ]
    if active_samples:
        start = active_samples[0].timestamp
        end = active_samples[-1].timestamp + timedelta(minutes=interval_minutes)
        figure.add_vrect(
            x0=start,
            x1=end,
            fillcolor="#D28A25",
            opacity=0.12,
            line_width=0,
            annotation_text="Evaluation ground truth",
            annotation_position="top left",
        )
    figure.update_layout(
        height=300,
        margin={"l": 15, "r": 15, "t": 35, "b": 15},
        title={"text": f"{metadata.label} · {cell_id}", "font": {"size": 15}},
        xaxis_title="UTC timestamp",
        yaxis_title=f"{metadata.short_label} ({metadata.unit})",
        hovermode="x unified",
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#F8FAFC",
    )
    figure.update_xaxes(showgrid=False, tickformat="%d %b<br>%H:%M")
    figure.update_yaxes(gridcolor="#E2E8F0", zeroline=False)
    return figure


def guardrail_rows(
    decision: ShadowDecision,
    thresholds: ThresholdSettings,
) -> list[dict[str, str]]:
    """Expose the existing guardrail outcome as an inspectable engineering table."""
    violations = decision.guardrail.violations

    def failed(*fragments: str) -> bool:
        return any(fragment in violation for fragment in fragments for violation in violations)

    def row(
        name: str,
        observed: str,
        threshold: str,
        failure: bool,
        explanation: str,
        *,
        escalate: bool = False,
    ) -> dict[str, str]:
        status = "Escalate" if escalate else ("Fail" if failure else "Pass")
        return {
            "Guardrail": name,
            "Observed or predicted": observed,
            "Configured threshold": threshold,
            "Status": status,
            "Explanation": explanation,
        }

    action = decision.action
    prediction = decision.prediction
    result = [
        row(
            "Action/prediction identity",
            "Matched" if action.action_id == prediction.action_id else "Mismatch",
            "Exact match",
            failed("identifiers do not match"),
            "The response must belong to the proposed action.",
        ),
        row(
            "Target-cell identity",
            f"{action.cell_id} / {prediction.cell_id}",
            "Exact match",
            failed("cells do not match"),
            "The response must reference the proposed target cell.",
        ),
    ]
    age_minutes = (decision.guardrail.evaluated_at - action.proposed_at).total_seconds() / 60
    result.append(
        row(
            "Telemetry freshness",
            f"{age_minutes:.1f} min at evaluation",
            f"≤ {thresholds.telemetry_max_age_minutes} min",
            failed("telemetry is stale", "timestamp is unacceptably far in the future"),
            "Fresh, timezone-aware evidence is required.",
        )
    )
    result.extend(
        [
            row(
                "Diagnosis confidence",
                f"{action.diagnosis_confidence:.0%}",
                f"≥ {thresholds.diagnosis_confidence_min:.0%}",
                failed("diagnosis confidence"),
                "Low-confidence diagnoses fail closed.",
            ),
            row(
                "Response confidence",
                f"{prediction.confidence:.0%}",
                f"≥ {thresholds.prediction_confidence_min:.0%}",
                failed("prediction confidence"),
                "Uncertain response estimates fail closed.",
            ),
        ]
    )

    if action.action_type is ActionType.ACTIVATE_CAPACITY:
        result.append(
            row(
                "Capacity action size",
                f"{float(action.parameters['capacity_delta_pct']):.1f}%",
                f"≤ {thresholds.max_capacity_increase_pct:.1f}%",
                failed("capacity increase"),
                "Capacity candidates are bounded by policy.",
            )
        )
    elif action.action_type is ActionType.STEER_TRAFFIC:
        result.append(
            row(
                "Traffic-steering size",
                f"{float(action.parameters['traffic_delta_pct']):.1f}%",
                f"≤ {thresholds.max_traffic_steering_pct:.1f}%",
                failed("traffic-steering percentage"),
                "Traffic shifts are bounded by policy.",
            )
        )
    elif action.action_type is ActionType.ROLLBACK_PARAMETER:
        delta = abs(
            float(action.parameters["previous_value"]) - float(action.parameters["current_value"])
        )
        result.append(
            row(
                "Configuration delta",
                f"{delta:.2f}",
                f"≤ {thresholds.max_parameter_delta:.2f}",
                failed("parameter delta"),
                "Rollback size is bounded by policy.",
            )
        )

    cells = [(action.cell_id, prediction.before_kpis, prediction.predicted_kpis)]
    cells.extend(
        (
            cell_id,
            prediction.impacted_cell_before_kpis[cell_id],
            values,
        )
        for cell_id, values in prediction.impacted_cell_kpis.items()
    )
    checks = (
        (
            "Handover success",
            "handover_success_pct",
            thresholds.handover_success_min_pct,
            "minimum",
            "handover success",
        ),
        (
            "RRC setup success",
            "rrc_success_pct",
            thresholds.rrc_success_min_pct,
            "minimum",
            "RRC success",
        ),
        (
            "Availability",
            "availability_pct",
            thresholds.availability_min_pct,
            "minimum",
            "availability is below",
        ),
        ("Latency", "latency_ms", thresholds.latency_max_ms, "maximum", "latency exceeds"),
        (
            "Call-drop rate",
            "call_drop_pct",
            thresholds.call_drop_max_pct,
            "maximum",
            "call-drop rate",
        ),
        ("BLER", "bler_pct", thresholds.bler_max_pct, "maximum", "BLER exceeds"),
    )
    for cell_id, before, predicted in cells:
        for label, field, threshold, kind, violation_text in checks:
            value = predicted[field]
            result.append(
                row(
                    f"{cell_id} · {label}",
                    format_kpi(field, value),
                    ("≥ " if kind == "minimum" else "≤ ") + format_kpi(field, threshold),
                    failed(f"{cell_id}: predicted {violation_text}"),
                    "Predicted service KPI must remain inside the configured boundary.",
                )
            )
        availability_drop = before["availability_pct"] - predicted["availability_pct"]
        result.append(
            row(
                f"{cell_id} · Availability change",
                f"{availability_drop:.3f} percentage points",
                f"≤ {thresholds.availability_max_drop_pct:.3f} percentage points",
                failed(f"{cell_id}: predicted availability decrease"),
                "A response cannot reduce availability beyond the configured margin.",
            )
        )

    result.append(
        row(
            "Human-review boundary",
            humanize_identifier(action.action_type.value),
            "No automated candidate requiring review",
            False,
            "Explicit review requests are escalated and cannot be approved.",
            escalate=action.action_type is ActionType.HUMAN_REVIEW,
        )
    )
    return result


def decision_label(status: DecisionStatus) -> str:
    return {
        DecisionStatus.SHADOW_APPROVED: "Approved for shadow reporting",
        DecisionStatus.SHADOW_REJECTED: "Rejected by guardrails",
        DecisionStatus.HUMAN_REVIEW: "Escalated for human review",
    }[status]
