import json
import logging
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
import uvicorn

from ai_ran_assurance.config import load_config
from ai_ran_assurance.investigation import (
    InvestigationMode,
    InvestigationService,
    ProviderUnavailableError,
    provider_from_name,
)
from ai_ran_assurance.simulation import KPIGenerator, build_network
from ai_ran_assurance.workflow import ClosedLoopEngine

app = typer.Typer(
    help="Synthetic, shadow-mode AI-assisted RAN assurance commands.",
    no_args_is_help=True,
)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
    )


@app.command("generate-data")
def generate_data(
    output: Annotated[Path, typer.Option(help="Output CSV path.")] = Path(
        "data/samples/normal_telemetry.csv"
    ),
    steps: Annotated[int, typer.Option(min=1, help="Number of five-minute intervals.")] = 72,
    seed: Annotated[int, typer.Option(help="Reproducible random seed.")] = 42,
) -> None:
    """Generate a small deterministic synthetic normal-telemetry dataset."""
    config = load_config()
    samples = KPIGenerator(build_network(config.network), config.network).generate(steps, seed=seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([sample.model_dump(mode="json") for sample in samples]).to_csv(output, index=False)
    typer.echo(f"wrote {len(samples)} synthetic samples to {output}")


@app.command()
def demo(
    scenario: Annotated[str, typer.Option(help="Configured fault scenario name.")] = "congestion",
) -> None:
    """Run telemetry through detection, diagnosis, twin simulation, and guardrails."""
    _configure_logging()
    result = ClosedLoopEngine().run(scenario)
    summary = {
        "scenario": scenario,
        "synthetic_data": True,
        "telemetry_samples": len(result.telemetry),
        "anomalies": len(result.anomalies),
        "diagnoses": [item.model_dump(mode="json") for item in result.diagnoses],
        "shadow_decisions": [item.model_dump(mode="json") for item in result.decisions],
    }
    typer.echo(json.dumps(summary, indent=2))


@app.command()
def benchmark() -> None:
    """Run the deterministic benchmark and write JSON and Markdown results."""
    from ai_ran_assurance.evaluation.benchmark import run_and_write_benchmark

    _configure_logging()
    results = run_and_write_benchmark()
    typer.echo(json.dumps(results, indent=2))


@app.command()
def investigate(
    scenario: Annotated[str, typer.Option(help="Configured synthetic replay scenario.")] = (
        "congestion"
    ),
    provider: Annotated[
        str,
        typer.Option(help="Provider: fixture (offline contract) or openai (explicit opt-in)."),
    ] = "fixture",
    cell: Annotated[
        str | None,
        typer.Option(help="Optional detected cell ID; defaults to observable anomaly ranking."),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(help="independent or review; independent is the evaluation default."),
    ] = "independent",
    export_context: Annotated[
        Path | None,
        typer.Option(help="Explicitly export the exact observable provider context as JSON."),
    ] = None,
) -> None:
    """Run advisory evidence-grounded investigation without changing the core decision."""
    _configure_logging()
    config = load_config()
    try:
        selected_mode = InvestigationMode(mode)
        selected_provider = provider_from_name(provider, config)
        run = ClosedLoopEngine(config).run(scenario)
        report = InvestigationService(config, selected_provider).investigate(
            topology=run.topology,
            telemetry=run.telemetry,
            anomalies=run.anomalies,
            cell_id=cell,
            mode=selected_mode,
            deterministic_diagnoses=run.diagnoses,
        )
    except (ValueError, ProviderUnavailableError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if export_context is not None:
        export_context.parent.mkdir(parents=True, exist_ok=True)
        export_context.write_text(report.context.model_dump_json(indent=2) + "\n", encoding="utf-8")
    typer.echo(report.model_dump_json(indent=2))


@app.command("evaluate-ai")
def evaluate_ai(
    provider: Annotated[
        str,
        typer.Option(help="fixture or an explicitly enabled live provider."),
    ] = "fixture",
    profile: Annotated[str, typer.Option(help="smoke or full evaluation profile.")] = "smoke",
    output_dir: Annotated[
        Path,
        typer.Option(help="Small reproducible evaluation-artifact directory."),
    ] = Path("reports/ai_evaluation"),
) -> None:
    """Evaluate investigation contracts; fixture results are not an AI benchmark."""
    from ai_ran_assurance.evaluation.ai_benchmark import run_and_write_ai_benchmark

    if profile not in {"smoke", "full"}:
        raise typer.BadParameter("profile must be 'smoke' or 'full'")
    _configure_logging()
    try:
        results = run_and_write_ai_benchmark(
            provider_name=provider,
            profile=profile,  # type: ignore[arg-type]
            output_dir=output_dir,
        )
    except ProviderUnavailableError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        json.dumps(
            {
                "evaluation_type": results["evaluation_type"],
                "profile": results["profile"],
                "metrics": results["metrics"],
                "output_dir": str(output_dir),
            },
            indent=2,
        )
    )


@app.command("serve-api")
def serve_api(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
) -> None:
    """Serve the FastAPI interface."""
    uvicorn.run("ai_ran_assurance.api.main:app", host=host, port=port)


if __name__ == "__main__":
    app()
