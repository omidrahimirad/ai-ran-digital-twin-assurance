from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from ai_ran_assurance.config import load_config
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


config = load_config()
scenario = st.sidebar.selectbox("Fault scenario", [item.name for item in config.scenarios])
if st.sidebar.button("Run scenario", type="primary") or "run" not in st.session_state:
    st.session_state.run = get_engine().run(scenario)

run = st.session_state.run
st.subheader("Network overview")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Cells", len(run.topology.cells))
col2.metric("Neighbor relations", len(run.topology.neighbor_relations))
col3.metric("Telemetry samples", len(run.telemetry))
col4.metric("Anomalies", len(run.anomalies))

frame = pd.DataFrame([item.model_dump(mode="json") for item in run.telemetry])
target = run.scenario.target_cells[0]
cell_frame = frame[frame["cell_id"] == target]
st.subheader(f"KPI time series — {target}")
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
