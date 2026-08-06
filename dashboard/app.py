"""Public Streamlit dashboard for the synthetic shadow-assurance workflow."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from ai_ran_assurance.config import ProjectConfig, load_config
from ai_ran_assurance.domain.enums import DecisionStatus, RootCauseCategory
from ai_ran_assurance.workflow import ClosedLoopEngine, ScenarioRun

try:
    from dashboard.presentation import (
        KPI_GROUPS,
        KPI_METADATA,
        SCENARIO_DESCRIPTIONS,
        APIStatus,
        build_safe_control_case,
        decision_label,
        detector_source,
        format_kpi,
        guardrail_rows,
        humanize_identifier,
        kpi_figure,
        load_json_object,
        probe_api_health,
        run_scenario,
        topology_figure,
    )
except ModuleNotFoundError:
    # Streamlit adds the script directory, rather than its parent, to sys.path.
    from presentation import (  # type: ignore[import-not-found,no-redef]
        KPI_GROUPS,
        KPI_METADATA,
        SCENARIO_DESCRIPTIONS,
        APIStatus,
        build_safe_control_case,
        decision_label,
        detector_source,
        format_kpi,
        guardrail_rows,
        humanize_identifier,
        kpi_figure,
        load_json_object,
        probe_api_health,
        run_scenario,
        topology_figure,
    )

REPOSITORY_URL = "https://github.com/omidrahimirad/ai-ran-digital-twin-assurance"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_URL = os.getenv("AI_RAN_API_URL", "http://127.0.0.1:8000")
PAGE_NAMES = (
    "Overview",
    "Scenario Explorer",
    "KPI Monitoring",
    "Detection and Diagnosis",
    "Action Evaluation",
    "Evaluation Results",
    "Scope and Assumptions",
)
REPRODUCED_TEST_COUNT = 83
REPRODUCED_BRANCH_COVERAGE = 94.52

st.set_page_config(
    page_title="AI-Assisted RAN Assurance",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_engine() -> ClosedLoopEngine:
    return ClosedLoopEngine()


@st.cache_resource
def get_safe_control() -> tuple[ScenarioRun, Any]:
    case = build_safe_control_case(ClosedLoopEngine(training_seed=17))
    return case.run, case.decision


@st.cache_data(ttl=10, show_spinner=False)
def get_api_status(base_url: str) -> APIStatus:
    return probe_api_health(base_url)


def render_header() -> None:
    st.title("AI-Assisted RAN Assurance")
    st.markdown(
        "#### Synthetic multi-cell monitoring, explainable diagnosis, and "
        "shadow-mode action validation"
    )
    st.info("Synthetic engineering prototype — no live-network ingestion or actuation")


def workflow_rows(run: ScenarioRun) -> list[dict[str, str]]:
    status_counts = {
        DecisionStatus.SHADOW_APPROVED: 0,
        DecisionStatus.SHADOW_REJECTED: 0,
        DecisionStatus.HUMAN_REVIEW: 0,
    }
    for decision in run.decisions:
        status_counts[decision.status] += 1
    final = (
        ", ".join(
            f"{count} {decision_label(status).lower()}"
            for status, count in status_counts.items()
            if count
        )
        or "No decision generated"
    )
    return [
        {"Stage": "Telemetry", "Current replay": f"{len(run.telemetry):,} KPI samples"},
        {"Stage": "Detection", "Current replay": f"{len(run.anomalies)} anomalies"},
        {"Stage": "Diagnosis", "Current replay": f"{len(run.diagnoses)} probable diagnoses"},
        {
            "Stage": "Recommendation",
            "Current replay": f"{len(run.recommendations)} candidates or escalations",
        },
        {
            "Stage": "Response simulation",
            "Current replay": f"{len(run.decisions)} copied-state evaluations",
        },
        {"Stage": "Guardrails", "Current replay": final},
        {"Stage": "Shadow report", "Current replay": "Non-executable output only"},
    ]


def render_overview(run: ScenarioRun, config: ProjectConfig) -> None:
    render_header()
    metrics = st.columns(5)
    metrics[0].metric("Simulated cells", len(run.topology.cells))
    metrics[1].metric("Configured scenarios", len(config.scenarios))
    metrics[2].metric("Latest detected anomalies", len(run.anomalies))
    metrics[3].metric("Current diagnoses", len(run.diagnoses))
    metrics[4].metric("Current shadow decisions", len(run.decisions))

    topology_column, workflow_column = st.columns([1.7, 1], gap="large")
    with topology_column:
        st.subheader("Configured network topology")
        st.caption(
            "Actual configured neighbor relations in a stable circular layout; positions are "
            "non-geographic. Amber rings identify injected evaluation targets after replay."
        )
        st.plotly_chart(
            topology_figure(run),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
            key="overview_topology",
        )
    with workflow_column:
        st.subheader("Current workflow status")
        st.dataframe(
            pd.DataFrame(workflow_rows(run)),
            hide_index=True,
            width="stretch",
            height=318,
        )
        st.caption(
            "Telemetry → detection → diagnosis → recommendation → response simulation → "
            "guardrails → shadow report"
        )

    does_column, does_not_column = st.columns(2, gap="large")
    with does_column, st.container(border=True):
        st.markdown("**What this system does**")
        st.markdown(
            "Processes deterministic synthetic KPI telemetry, retains ambiguous evidence, "
            "and evaluates candidate actions against copied state and fail-closed policy."
        )
    with does_not_column, st.container(border=True):
        st.markdown("**What it does not do**")
        st.markdown(
            "It does not ingest a live network, implement an O-RAN RIC, predict RF behavior, "
            "or send configuration commands."
        )

    api_status = get_api_status(API_URL)
    if api_status.available:
        st.caption(f"API status: {api_status.label} — {api_status.detail}")
    else:
        st.warning(
            f"Optional API status: {api_status.label}. {api_status.detail} "
            "The embedded deterministic workflow remains available."
        )


def _request_reset() -> None:
    st.session_state["reset_requested"] = True


def render_scenario_explorer(run: ScenarioRun, config: ProjectConfig) -> ScenarioRun:
    render_header()
    st.subheader("Scenario Explorer")
    st.write(
        "Configure a deterministic replay. Scenario injection truth is displayed separately "
        "from evidence available to the operational workflow."
    )

    first, second, third = st.columns([1.3, 1, 1])
    scenario_names = [item.name for item in config.scenarios]
    with first:
        selected_name = st.selectbox(
            "Configured scenario",
            scenario_names,
            key="scenario_control",
            format_func=humanize_identifier,
        )
    selected = config.scenario(selected_name)
    with second:
        severity = st.slider(
            "Injection severity",
            min_value=0.10,
            max_value=1.00,
            value=float(selected.severity),
            step=0.05,
            key=f"severity_control_{selected_name}",
            help="Validated synthetic fault intensity; it is not a field-calibrated scale.",
        )
    with third:
        seed = int(
            st.number_input(
                "Evaluation seed",
                min_value=0,
                max_value=1_000_000,
                value=config.network.seed + 1,
                step=1,
                key=f"seed_control_{selected_name}",
                help="Equal configuration and seed produce equal synthetic telemetry.",
            )
        )

    st.caption(SCENARIO_DESCRIPTIONS[selected_name])
    st.caption(
        "Directly modified synthetic KPIs: "
        + ", ".join(KPI_METADATA[field].short_label for field in selected.affected_kpis)
    )

    run_column, reset_column, _ = st.columns([1, 1, 4])
    with run_column:
        run_clicked = st.button("Run Scenario", type="primary", width="stretch")
    with reset_column:
        st.button("Reset", on_click=_request_reset, width="stretch")
    if run_clicked:
        with st.spinner("Running deterministic synthetic replay…"):
            run = run_scenario(
                get_engine(),
                selected_name,
                severity=float(severity),
                seed=seed,
            )
        st.session_state["current_run"] = run
        st.success(
            f"Replay completed: {len(run.telemetry):,} samples, "
            f"{len(run.anomalies)} anomalies, {len(run.decisions)} shadow decisions."
        )
    elif (
        run.scenario.name != selected_name
        or abs(run.scenario.severity - float(severity)) > 1e-9
        or run.evaluation_seed != seed
    ):
        st.info(
            "Controls have changed. Select Run Scenario to replace the current replay; "
            f"displayed results remain {run.scenario.name}, severity {run.scenario.severity:.2f}, "
            f"seed {run.evaluation_seed}."
        )

    st.subheader("Latest completed replay")
    summary = st.columns(4)
    summary[0].metric("Scenario", humanize_identifier(run.scenario.name))
    summary[1].metric("Severity", f"{run.scenario.severity:.2f}")
    summary[2].metric("Evaluation seed", run.evaluation_seed)
    summary[3].metric("Telemetry samples", f"{len(run.telemetry):,}")

    evidence_column, truth_column = st.columns(2, gap="large")
    with evidence_column, st.container(border=True):
        st.markdown("**Operational workflow evidence**")
        st.write(f"Detected anomalies: {len(run.anomalies)}")
        st.write(f"Probable diagnoses: {len(run.diagnoses)}")
        st.write(f"Shadow decisions: {len(run.decisions)}")
        st.caption("These outputs are derived from KPI evidence without scenario labels.")
    with truth_column, st.container(border=True):
        st.markdown("**Injected evaluation ground truth**")
        st.write(f"Target cells: {', '.join(run.scenario.target_cells)}")
        st.write(f"Injected category: {humanize_identifier(run.scenario.ground_truth.value)}")
        st.write(
            f"Active steps: {run.scenario.start_step}–"
            f"{run.scenario.start_step + run.scenario.duration - 1}"
        )
        st.caption("Evaluator-only context; it is not detector or diagnosis input.")
    return run


def render_kpi_monitoring(run: ScenarioRun, config: ProjectConfig) -> None:
    render_header()
    st.subheader("KPI Monitoring")
    if not run.telemetry:
        st.info("No telemetry is available. Run a scenario to populate KPI monitoring.")
        return

    cell_ids = [cell.cell_id for cell in run.topology.cells]
    detected_cell = run.anomalies[0].cell_id if run.anomalies else cell_ids[0]
    cell_column, group_column, kpi_column = st.columns([1, 1.25, 1.5])
    with cell_column:
        cell_id = st.selectbox(
            "Cell",
            cell_ids,
            index=cell_ids.index(detected_cell),
            key="kpi_cell",
        )
    with group_column:
        group = st.selectbox("KPI group", list(KPI_GROUPS), key="kpi_group")
    fields = KPI_GROUPS[group]
    with kpi_column:
        field = st.selectbox(
            "Metric",
            fields,
            format_func=lambda item: KPI_METADATA[item].label,
            key=f"kpi_field_{group}",
        )

    st.plotly_chart(
        kpi_figure(
            run,
            cell_id=cell_id,
            field=field,
            thresholds=config.thresholds,
            interval_minutes=config.network.interval_minutes,
        ),
        width="stretch",
        config={"displayModeBar": False, "responsive": True},
        key=f"kpi_chart_{cell_id}_{field}",
    )
    samples = [item for item in run.telemetry if item.cell_id == cell_id]
    latest = float(getattr(samples[-1], field))
    metadata = KPI_METADATA[field]
    detail_columns = st.columns(3)
    detail_columns[0].metric("Latest value", format_kpi(field, latest))
    detail_columns[1].metric("Samples", len(samples))
    if metadata.threshold_field is not None:
        threshold = float(getattr(config.thresholds, metadata.threshold_field))
        detail_columns[2].metric(
            f"Policy {metadata.threshold_kind}",
            format_kpi(field, threshold),
        )
    if cell_id in run.scenario.target_cells:
        st.caption(
            "The amber chart overlay is evaluation ground truth for the injected interval; "
            "it is not detector input."
        )
    else:
        st.caption(
            "No evaluation-ground-truth overlay is shown because this cell is not an "
            "injected target."
        )


def _evidence_text(evidence: dict[str, float]) -> str:
    return "; ".join(
        f"{KPI_METADATA[field].short_label}: {format_kpi(field, value)}"
        for field, value in evidence.items()
    )


def render_detection_and_diagnosis(run: ScenarioRun) -> None:
    render_header()
    st.subheader("Detection and Diagnosis")
    if not run.anomalies:
        st.info("No anomalies were detected in the current replay. No diagnosis is available.")
        return

    anomaly_rows = [
        {
            "Timestamp (UTC)": item.timestamp.strftime("%Y-%m-%d %H:%M"),
            "Cell": item.cell_id,
            "Anomaly type": humanize_identifier(item.anomaly_type.value),
            "Detection source": detector_source(item),
            "Score": f"{item.score:.3f}",
            "KPI evidence": _evidence_text(item.evidence),
        }
        for item in run.anomalies
    ]
    st.dataframe(pd.DataFrame(anomaly_rows), hide_index=True, width="stretch", height=280)
    st.caption(
        "Scores are detector-specific magnitudes, not calibrated probabilities. Statistical "
        "findings enter the workflow only with Isolation Forest agreement."
    )

    if not run.diagnoses:
        st.info("Anomalies are present, but no diagnosis was produced for the current replay.")
        return
    diagnosis_index = st.selectbox(
        "Diagnosis record",
        list(range(len(run.diagnoses))),
        format_func=lambda index: (
            f"{run.diagnoses[index].cell_id} · "
            f"{run.diagnoses[index].timestamp.strftime('%Y-%m-%d %H:%M UTC')}"
        ),
    )
    diagnosis = run.diagnoses[diagnosis_index]
    st.markdown("#### Evidence-supported probable diagnosis")
    metrics = st.columns(3)
    metrics[0].metric("Probable category", humanize_identifier(diagnosis.probable_root_cause.value))
    metrics[1].metric("Diagnosis confidence", f"{diagnosis.confidence:.0%}")
    metrics[2].metric("Evidence KPIs", len(diagnosis.evidence_kpis))
    if diagnosis.probable_root_cause is RootCauseCategory.UNKNOWN:
        st.warning("Unresolved mobility evidence — requires human review.")
    st.write(diagnosis.explanation)
    st.markdown(f"**Recommended next diagnostic check:** {diagnosis.next_diagnostic_check}")
    if diagnosis.evidence_kpis:
        evidence_rows = [
            {
                "KPI": KPI_METADATA[field].label,
                "Observed value": format_kpi(field, value),
            }
            for field, value in diagnosis.evidence_kpis.items()
        ]
        st.dataframe(pd.DataFrame(evidence_rows), hide_index=True, width="stretch")
    else:
        st.info("The diagnosis did not retain a KPI value as sufficiently specific evidence.")


def _decision_banner(decision: Any) -> None:
    label = decision_label(decision.status)
    if decision.status is DecisionStatus.SHADOW_APPROVED:
        st.success(f"{label} — shadow output only; no actuation path exists.")
    elif decision.status is DecisionStatus.SHADOW_REJECTED:
        st.error(f"{label} — the candidate remains non-executable.")
    else:
        st.warning(f"{label} — further engineering review is required.")


def render_action_evaluation(run: ScenarioRun, config: ProjectConfig) -> None:
    render_header()
    st.subheader("Action Evaluation")
    demonstration = st.radio(
        "Demonstration",
        ("Current scenario outcome", "Fresh high-confidence safe-control regression"),
        horizontal=True,
        help="Both paths execute the existing response surrogate and guardrail validator.",
    )
    if demonstration == "Fresh high-confidence safe-control regression":
        with st.spinner("Reproducing safe-control regression…"):
            source_run, decision = get_safe_control()
        st.info(
            "Guardrail regression control: congestion seed 101 with fresh evidence and "
            "explicit 90% diagnosis/response confidence, matching the benchmark code path."
        )
        run = source_run
    else:
        if not run.decisions:
            st.info("No candidate action or escalation exists for the current replay.")
            return
        decision_index = st.selectbox(
            "Decision record",
            list(range(len(run.decisions))),
            format_func=lambda index: (
                f"{run.decisions[index].action.cell_id} · "
                f"{humanize_identifier(run.decisions[index].action.action_type.value)}"
            ),
        )
        decision = run.decisions[decision_index]

    _decision_banner(decision)
    action = decision.action
    prediction = decision.prediction
    impacted = sorted(prediction.impacted_cell_kpis)
    action_columns = st.columns(5)
    action_columns[0].metric("Candidate action", humanize_identifier(action.action_type.value))
    action_columns[1].metric("Target cell", action.cell_id)
    action_columns[2].metric("Impacted cells", ", ".join(impacted) if impacted else "None")
    action_columns[3].metric("Diagnosis confidence", f"{action.diagnosis_confidence:.0%}")
    action_columns[4].metric("Response confidence", f"{prediction.confidence:.0%}")
    st.caption(action.rationale)

    st.markdown("#### Current state and simulated response")
    comparison = pd.DataFrame(
        [
            {
                "KPI": KPI_METADATA[field].label,
                "Current state": format_kpi(field, before),
                "Simulated response": format_kpi(field, prediction.predicted_kpis[field]),
                "Numeric delta": round(prediction.predicted_kpis[field] - before, 4),
            }
            for field, before in prediction.before_kpis.items()
        ]
    )
    st.dataframe(comparison, hide_index=True, width="stretch", height=300)
    if impacted:
        st.caption("Impacted-cell KPI vectors are included in the guardrail table below.")
    with st.expander("Response-model assumptions and boundary", expanded=False):
        st.write(prediction.model_description)
        for assumption in prediction.assumptions:
            st.markdown(f"- {assumption}")

    st.markdown("#### Guardrail decision record")
    rows = guardrail_rows(decision, config.thresholds)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=370)
    if decision.guardrail.violations:
        st.markdown("**Recorded rejection or escalation reasons**")
        for violation in decision.guardrail.violations:
            st.markdown(f"- {violation}")
    else:
        st.success("All modeled guardrail checks passed for this regression control.")
    st.caption(decision.note)


def render_evaluation_results() -> None:
    render_header()
    st.subheader("Reproduced Evaluation Results")
    results, results_error = load_json_object(REPOSITORY_ROOT / "artifacts/sample_results.json")
    if results_error or results is None:
        st.error(results_error or "The committed benchmark artifact is unavailable.")
        return
    try:
        detection = results["detection"]
        root_cause = results["root_cause"]
        regression = results["guardrail_regression"]
        metric_values = (
            float(results["fault_episode_detection_rate"]),
            float(detection["precision"]),
            float(detection["recall"]),
            float(detection["f1_score"]),
            float(root_cause["accuracy_on_diagnosed_episodes"]),
            int(root_cause["ambiguous_episodes"]),
            int(regression["cases_rejected_or_escalated"]),
            int(regression["unsafe_or_escalation_cases"]),
            int(regression["safe_control_approved"]),
        )
    except (KeyError, TypeError, ValueError):
        st.error("The committed benchmark artifact does not match the expected result schema.")
        return

    st.warning(
        "Results apply only to the included deterministic synthetic closed-set scenarios and "
        "are not evidence of performance on a commercial mobile network."
    )
    first_row = st.columns(5)
    first_row[0].metric("Fault-episode detection", f"{metric_values[0]:.2%}")
    first_row[1].metric("Precision", f"{metric_values[1]:.4f}")
    first_row[2].metric("Recall", f"{metric_values[2]:.4f}")
    first_row[3].metric("F1", f"{metric_values[3]:.4f}")
    first_row[4].metric("RCA accuracy", f"{metric_values[4]:.2%}")
    second_row = st.columns(5)
    second_row[0].metric("Ambiguous diagnoses", metric_values[5])
    second_row[1].metric(
        "Unsafe/escalation cases",
        f"{metric_values[6]}/{metric_values[7]} rejected",
    )
    second_row[2].metric("Safe control", f"{metric_values[8]} approved")
    second_row[3].metric("Tests", f"{REPRODUCED_TEST_COUNT} passing")
    second_row[4].metric("Branch coverage", f"{REPRODUCED_BRANCH_COVERAGE:.2f}%")
    st.caption(
        "Precision must be read with recall and episode detection. RCA accuracy covers diagnosed "
        "episodes only; ambiguous evidence remains visible rather than forced into a cause."
    )

    scenario_rows = [
        {
            "Scenario": humanize_identifier(name),
            "Episodes": values["episodes"],
            "Detected": values["detected_episodes"],
            "Correct RCA": values["correct_root_causes"],
            "Ambiguous RCA": values["ambiguous_root_causes"],
        }
        for name, values in results["scenarios"].items()
    ]
    st.markdown("#### Scenario-level outcomes")
    st.dataframe(pd.DataFrame(scenario_rows), hide_index=True, width="stretch")
    st.link_button(
        "Full evaluation protocol and interpretation",
        f"{REPOSITORY_URL}/blob/main/docs/results.md",
    )


def render_scope_and_assumptions() -> None:
    render_header()
    st.subheader("Scope and Assumptions")
    scope_rows = (
        ("Data source", "Deterministic synthetic telemetry; no operator dataset or live feed."),
        ("Radio model", "No RF propagation, fading, scheduler, UE, bearer, or packet model."),
        ("Standards", "No standards compliance claim and no O-RAN interface or RIC."),
        ("Actuation", "No southbound client; no candidate can be sent to a network."),
        (
            "State model",
            "Copied topology/configuration/KPI state with deterministic bounded response "
            "equations.",
        ),
        (
            "Calibration",
            "Thresholds, diagnosis weights, response factors, and confidence values are "
            "illustrative.",
        ),
    )
    st.dataframe(
        pd.DataFrame(scope_rows, columns=["Boundary", "What applies here"]),
        hide_index=True,
        width="stretch",
    )
    st.markdown("#### Detailed documentation")
    links = (
        ("Architecture and safety boundary", "docs/architecture.md"),
        ("Methodology", "docs/methodology.md"),
        ("Assumptions", "docs/assumptions.md"),
        ("Limitations", "docs/limitations.md"),
        ("Reproduced results", "docs/results.md"),
        ("Future-RAN and standards boundaries", "docs/six_g_alignment.md"),
    )
    for label, path in links:
        st.markdown(f"- [{label}]({REPOSITORY_URL}/blob/main/{path})")


config = load_config()
if st.session_state.pop("reset_requested", False):
    default_scenario = config.scenario("congestion")
    for key in list(st.session_state):
        if key == "scenario_control" or (
            isinstance(key, str) and key.startswith(("severity_control_", "seed_control_"))
        ):
            del st.session_state[key]
    st.session_state["current_run"] = get_engine().run(
        default_scenario.name,
        seed=config.network.seed + 1,
    )
if "current_run" not in st.session_state:
    with st.spinner("Preparing deterministic synthetic replay…"):
        st.session_state["current_run"] = get_engine().run(
            "congestion",
            seed=config.network.seed + 1,
        )

current_run: ScenarioRun = st.session_state["current_run"]
st.sidebar.markdown("### Assurance demonstrator")
page = st.sidebar.radio("View", PAGE_NAMES, index=0)
st.sidebar.divider()
st.sidebar.caption("Current synthetic replay")
st.sidebar.write(f"**Scenario:** {humanize_identifier(current_run.scenario.name)}")
st.sidebar.write(f"**Seed:** {current_run.evaluation_seed}")
st.sidebar.write(f"**Mode:** {humanize_identifier(current_run.evaluation_mode)}")
st.sidebar.caption("Shadow reporting only · no network actuation")

if page == "Overview":
    render_overview(current_run, config)
elif page == "Scenario Explorer":
    current_run = render_scenario_explorer(current_run, config)
elif page == "KPI Monitoring":
    render_kpi_monitoring(current_run, config)
elif page == "Detection and Diagnosis":
    render_detection_and_diagnosis(current_run)
elif page == "Action Evaluation":
    render_action_evaluation(current_run, config)
elif page == "Evaluation Results":
    render_evaluation_results()
else:
    render_scope_and_assumptions()
