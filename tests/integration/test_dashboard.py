from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_renders_engineering_investigation_not_chatbot() -> None:
    dashboard = Path(__file__).parents[2] / "dashboard/app.py"
    app = AppTest.from_file(dashboard, default_timeout=20).run()
    assert not app.exception
    assert app.title[0].value == "Synthetic AI-Assisted RAN Assurance"
    assert any("Advisory AI investigation" in item.value for item in app.subheader)
    assert any("cannot modify the shadow decision" in item.value for item in app.info)
    button = next(
        item for item in app.button if item.label == "Run evidence-grounded fixture investigation"
    )
    app = button.click().run()
    assert not app.exception
    assert any(item.label == "Primary hypothesis" for item in app.metric)
    assert any(item.label == "Status" for item in app.metric)
