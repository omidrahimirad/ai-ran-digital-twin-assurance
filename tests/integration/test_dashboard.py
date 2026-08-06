from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[2] / "dashboard/app.py"
PAGES = (
    "Overview",
    "Scenario Explorer",
    "KPI Monitoring",
    "Detection and Diagnosis",
    "Action Evaluation",
    "Evaluation Results",
    "Scope and Assumptions",
)
SCENARIOS = (
    "congestion",
    "interference",
    "missing_neighbor",
    "outage",
    "transport_latency",
    "coverage",
    "bler",
    "mobility",
)


def _dashboard() -> AppTest:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=30)
    assert not app.exception
    return app


def test_dashboard_renders_all_sections_scenarios_and_empty_states() -> None:
    app = _dashboard()
    for page in PAGES:
        app.sidebar.radio[0].set_value(page).run(timeout=30)
        assert not app.exception, page

    app.sidebar.radio[0].set_value("Scenario Explorer").run(timeout=30)
    scenario = next(item for item in app.selectbox if item.label == "Configured scenario")
    for scenario_name in SCENARIOS:
        scenario.set_value(scenario_name).run(timeout=30)
        assert not app.exception, scenario_name
        scenario = next(item for item in app.selectbox if item.label == "Configured scenario")
        assert scenario.value == scenario_name

    run = app.session_state["current_run"]
    app.session_state["current_run"] = run.model_copy(
        update={"anomalies": [], "diagnoses": [], "recommendations": [], "decisions": []}
    )
    app.sidebar.radio[0].set_value("Detection and Diagnosis").run(timeout=30)
    assert any("No anomalies were detected" in item.value for item in app.info)
    app.sidebar.radio[0].set_value("Action Evaluation").run(timeout=30)
    assert any("No candidate action" in item.value for item in app.info)


def test_dashboard_renders_rejected_and_safe_approved_paths() -> None:
    app = _dashboard()
    app.sidebar.radio[0].set_value("Action Evaluation").run(timeout=30)

    assert any("Rejected by guardrails" in item.value for item in app.error)
    demonstration = next(item for item in app.radio if item.label == "Demonstration")
    demonstration.set_value("Fresh high-confidence safe-control regression").run(timeout=30)

    assert not app.exception
    assert any("Approved for shadow reporting" in item.value for item in app.success)
    assert any("All modeled guardrail checks passed" in item.value for item in app.success)


def test_dashboard_renders_ambiguous_mobility_human_review() -> None:
    app = _dashboard()
    app.sidebar.radio[0].set_value("Scenario Explorer").run(timeout=30)
    scenario = next(item for item in app.selectbox if item.label == "Configured scenario")
    scenario.set_value("mobility").run(timeout=30)
    run_button = next(item for item in app.button if item.label == "Run Scenario")
    run_button.click().run(timeout=30)

    assert not app.exception
    assert app.session_state["current_run"].scenario.name == "mobility"
    app.sidebar.radio[0].set_value("Detection and Diagnosis").run(timeout=30)
    assert any("Unresolved mobility evidence" in item.value for item in app.warning)
    app.sidebar.radio[0].set_value("Action Evaluation").run(timeout=30)
    assert any("Escalated for human review" in item.value for item in app.warning)


def test_dashboard_reports_unavailable_api_without_losing_embedded_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_RAN_API_URL", "http://127.0.0.1:1")

    app = _dashboard()

    assert any("Optional API status: Unavailable" in item.value for item in app.warning)
    assert any(item.label == "Latest detected anomalies" for item in app.metric)
