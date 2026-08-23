from pathlib import Path

from typer.testing import CliRunner

from ai_ran_assurance import cli

runner = CliRunner()


def test_generate_data_command(tmp_path: Path) -> None:
    output = tmp_path / "telemetry.csv"
    result = runner.invoke(cli.app, ["generate-data", "--output", str(output), "--steps", "2"])
    assert result.exit_code == 0
    assert "40 synthetic samples" in result.stdout
    assert output.exists()


def test_demo_and_help_commands() -> None:
    help_result = runner.invoke(cli.app, ["--help"])
    assert help_result.exit_code == 0
    assert "generate-data" in help_result.stdout
    demo_result = runner.invoke(cli.app, ["demo", "--scenario", "bler"])
    assert demo_result.exit_code == 0
    assert '"synthetic_data": true' in demo_result.stdout


def test_benchmark_and_serve_commands(monkeypatch: object) -> None:
    import ai_ran_assurance.evaluation.benchmark as benchmark_module

    monkeypatch.setattr(benchmark_module, "run_and_write_benchmark", lambda: {"ok": True})
    benchmark_result = runner.invoke(cli.app, ["benchmark"])
    assert benchmark_result.exit_code == 0
    assert '"ok": true' in benchmark_result.stdout

    called: dict[str, object] = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: called.update(kwargs))
    serve_result = runner.invoke(cli.app, ["serve-api", "--host", "127.0.0.1", "--port", "9999"])
    assert serve_result.exit_code == 0
    assert called == {"host": "127.0.0.1", "port": 9999}


def test_investigate_exports_exact_leakage_safe_context(tmp_path: Path) -> None:
    import json

    context_path = tmp_path / "context.json"
    result = runner.invoke(
        cli.app,
        [
            "investigate",
            "--scenario",
            "congestion",
            "--provider",
            "fixture",
            "--export-context",
            str(context_path),
        ],
    )
    assert result.exit_code == 0
    assert '"advisory_only": true' in result.stdout
    context = json.loads(context_path.read_text(encoding="utf-8"))
    serialized = str(context)
    for forbidden in ("ground_truth", "target_cells", "fault_type", "severity"):
        assert forbidden not in serialized
    assert context["metadata"]["future_telemetry_excluded"] is True


def test_evaluate_ai_command_labels_fixture_contract(monkeypatch: object, tmp_path: Path) -> None:
    import ai_ran_assurance.evaluation.ai_benchmark as ai_benchmark_module

    monkeypatch.setattr(
        ai_benchmark_module,
        "run_and_write_ai_benchmark",
        lambda **_: {
            "evaluation_type": "deterministic_fixture_contract",
            "profile": "smoke",
            "metrics": {"case_count": 8},
        },
    )
    result = runner.invoke(
        cli.app,
        ["evaluate-ai", "--provider", "fixture", "--output-dir", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "deterministic_fixture_contract" in result.stdout


def test_live_cli_paths_are_disabled_by_default() -> None:
    result = runner.invoke(
        cli.app,
        ["investigate", "--scenario", "congestion", "--provider", "openai"],
    )
    assert result.exit_code == 2
    assert "live provider disabled" in result.output
