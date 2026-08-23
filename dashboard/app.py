from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from ai_ran_assurance.config import load_config
from ai_ran_assurance.investigation import FixtureProvider, InvestigationService, select_anomaly
from ai_ran_assurance.workflow import ClosedLoopEngine

st.set_page_config(page_title="Synthetic RAN Assurance", layout="wide")
st.title("Synthetic AI-Assisted RAN Assurance")
st.warning(
    "Simulation-based prototype using deterministic synthetic RAN data. "
    "All decisions remain in shadow mode."
)


@st.cache_resource
def get_engine() -> ClosedLoopEngine:
    return ClosedLoopEngine()


@st.cache_resource
def get_investigation_service() -> InvestigationService:
    return InvestigationService(load_config(), FixtureProvider())


config = load_config()
scenario = st.sidebar.selectbox("Fault scenario", [item.name for item in config.scenarios])
if st.sidebar.button("Run scenario", type="primary") or "run" not in st.session_state:
    st.session_state.run = get_engine().run(scenario)
    st.session_state.pop("investigation_report", None)

run = st.session_state.run
st.subheader("Network overview")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Cells", len(run.topology.cells))
col2.metric("Neighbor relations", len(run.topology.neighbor_relations))
col3.metric("Telemetry samples", len(run.telemetry))
col4.metric("Anomalies", len(run.anomalies))

frame = pd.DataFrame([item.model_dump(mode="json") for item in run.telemetry])
observed_cell = select_anomaly(run.anomalies).cell_id
cell_frame = frame[frame["cell_id"] == observed_cell]
st.subheader(f"KPI time series — detected cell {observed_cell}")
selected_kpis = st.multiselect(
    "KPIs",
    [
        "prb_utilization_pct",
        "throughput_mbps",
        "latency_ms",
        "bler_pct",
        "handover_success_pct",
    ],
    default=["prb_utilization_pct", "throughput_mbps", "latency_ms"],
)
st.plotly_chart(
    px.line(cell_frame, x="timestamp", y=selected_kpis, title="Synthetic KPI evolution"),
    width="stretch",
)

st.subheader("Anomalies")
st.dataframe(pd.DataFrame([item.model_dump(mode="json") for item in run.anomalies]))

left, right = st.columns(2)
with left:
    st.subheader("Explainable root causes")
    for diagnosis in run.diagnoses:
        st.markdown(f"**{diagnosis.probable_root_cause.value}** ({diagnosis.confidence:.0%})")
        st.write(diagnosis.explanation)
        st.caption(f"Next check: {diagnosis.next_diagnostic_check}")
with right:
    st.subheader("Proposed shadow actions")
    for decision in run.decisions:
        st.write(decision.action.action_type.value)
        st.write(f"Status: `{decision.status.value}`")
        st.write("Guardrails:", decision.guardrail.violations or ["passed"])

st.subheader("Advisory AI investigation")
st.info(
    "AI investigation is advisory and cannot modify the shadow decision or execute "
    "network actions. The offline fixture demonstrates contracts, not LLM performance."
)
detected_cells = sorted({item.cell_id for item in run.anomalies})
selected_cell = st.selectbox("Detected cell to investigate", detected_cells)
if st.button("Run evidence-grounded fixture investigation"):
    st.session_state.investigation_report = get_investigation_service().investigate(
        topology=run.topology,
        telemetry=run.telemetry,
        anomalies=run.anomalies,
        cell_id=selected_cell,
    )

report = st.session_state.get("investigation_report")
if report is not None and report.context.analyzed_cell == selected_cell:
    deterministic = next(
        (item for item in run.diagnoses if item.cell_id == selected_cell),
        None,
    )
    evidence_column, investigation_column = st.columns(2)
    with evidence_column:
        st.markdown("#### Deterministic evidence")
        st.write(
            {
                "analyzed_timestamp": report.context.analyzed_timestamp.isoformat(),
                "anomaly_type": report.context.anomaly.anomaly_type.value,
                "detector": report.context.anomaly.detector,
                "anomaly_score": report.context.anomaly.score,
                "KPI_evidence": {
                    key: f"{value.value} {value.unit}"
                    for key, value in report.context.anomaly.evidence.items()
                },
            }
        )
        if deterministic is not None:
            st.caption("Existing deterministic per-cell RCA candidate (not ground truth)")
            st.write(
                {
                    "probable_category": deterministic.probable_root_cause.value,
                    "confidence": deterministic.confidence,
                    "next_check": deterministic.next_diagnostic_check,
                }
            )
    with investigation_column:
        st.markdown("#### AI investigation")
        if report.investigation is None:
            st.error(report.failure_reason or "Provider output was rejected.")
        else:
            output = report.investigation.output
            st.metric("Primary hypothesis", output.primary_hypothesis.value)
            st.write(f"Abstained: **{output.abstained}**")
            st.caption(output.uncertainty_explanation)
            for hypothesis in output.hypotheses:
                with st.expander(
                    f"{hypothesis.category.value} — {hypothesis.confidence:.0%}",
                    expanded=hypothesis.category is output.primary_hypothesis,
                ):
                    st.write(hypothesis.explanation)
                    st.write("Supporting evidence:", hypothesis.supporting_evidence_ids)
                    st.write("Competing/counter evidence:", hypothesis.counter_evidence_ids)
                    st.write("Missing evidence:", hypothesis.missing_evidence)
                    st.write("Next checks:", hypothesis.next_diagnostic_checks)

    knowledge_column, verification_column = st.columns(2)
    with knowledge_column:
        st.markdown("#### Retrieved engineering knowledge")
        for item in report.context.retrieved_knowledge:
            st.markdown(f"**{item.chunk_id} — {item.heading}**")
            st.caption(f"{item.source_path} · relevance {item.relevance_score:.3f}")
    with verification_column:
        st.markdown("#### Deterministic verification")
        st.metric("Status", report.verification.status.value.upper())
        st.write("Invalid evidence references:", report.verification.invalid_evidence_references)
        st.write("Invalid citations:", report.verification.invalid_knowledge_citations)
        st.write("Grounding warnings:", report.verification.unsupported_claims)
        st.write("Safety violations:", report.verification.safety_policy_violations)
    with st.expander("Inspect exact provider context"):
        st.json(report.context.model_dump(mode="json"))

st.subheader("Before and surrogate-after copied state")
for decision in run.decisions:
    comparison = pd.DataFrame(
        {
            "KPI": list(decision.prediction.before_kpis),
            "Before": list(decision.prediction.before_kpis.values()),
            "Predicted after": list(decision.prediction.predicted_kpis.values()),
        }
    )
    st.dataframe(comparison, hide_index=True)

results_path = Path("artifacts/sample_results.json")
st.subheader("Benchmark metrics")
if results_path.exists():
    st.json(results_path.read_text(encoding="utf-8"))
else:
    st.info("Run `python -m ai_ran_assurance.cli benchmark` to generate benchmark metrics.")
