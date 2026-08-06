import json
import logging
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
import uvicorn

from ai_ran_assurance.config import load_config
from ai_ran_assurance.simulation import KPIGenerator, build_network
from ai_ran_assurance.workflow import ClosedLoopEngine

app = typer.Typer(
    help="Synthetic, shadow-mode AI-assisted RAN digital-twin assurance commands.",
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


@app.command("serve-api")
def serve_api(
    host: Annotated[str, typer.Option(help="Bind host.")] = "0.0.0.0",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8000,
) -> None:
    """Serve the FastAPI interface."""
    uvicorn.run("ai_ran_assurance.api.main:app", host=host, port=port)


if __name__ == "__main__":
    app()
