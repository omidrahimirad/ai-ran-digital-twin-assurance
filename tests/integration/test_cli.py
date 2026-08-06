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
