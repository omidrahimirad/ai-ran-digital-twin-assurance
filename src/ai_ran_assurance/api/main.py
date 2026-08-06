import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from ai_ran_assurance.api.schemas import (
    ActionValidationRequest,
    ActionValidationResponse,
    ScenarioRunRequest,
    ScenarioRunResponse,
)
from ai_ran_assurance.domain.models import (
    Anomaly,
    Cell,
    CorrectiveAction,
    KPISample,
    NetworkTopology,
    RootCauseDiagnosis,
    ShadowDecision,
)
from ai_ran_assurance.twin import (
    ActionSimulationError,
    GuardrailValidator,
    NetworkTwin,
    TwinSimulator,
)
from ai_ran_assurance.workflow import ClosedLoopEngine, ScenarioRun

REQUESTS = Counter("ai_ran_api_requests_total", "API requests", ["path", "method"])
LATENCY = Histogram("ai_ran_api_latency_seconds", "API latency", ["path"])
LOGGER = logging.getLogger(__name__)


class AppState:
    engine: ClosedLoopEngine | None = None
    latest: ScenarioRun | None = None
    lock = Lock()


STATE = AppState()


def engine() -> ClosedLoopEngine:
    if STATE.engine is None:
        STATE.engine = ClosedLoopEngine()
    return STATE.engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    engine()
    yield


app = FastAPI(
    title="Synthetic AI-Assisted RAN Assurance",
    description="Synthetic-data shadow assurance with a bounded response surrogate.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def observe(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    method = request.method
    started = time.perf_counter()
    try:
        return await call_next(request)
    finally:
        # Route templates bound Prometheus label cardinality; raw paths let arbitrary
        # 404 requests create an unbounded time series.
        path = str(getattr(request.scope.get("route"), "path", "unmatched"))
        REQUESTS.labels(path=path, method=method).inc()
        LATENCY.labels(path=path).observe(time.perf_counter() - started)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "mode": "shadow", "synthetic_data": True}


@app.get("/cells", response_model=list[Cell])
def cells() -> list[Cell]:
    return engine().topology.cells


@app.get("/network", response_model=NetworkTopology)
def network() -> NetworkTopology:
    return engine().topology


@app.post("/scenarios/run", response_model=ScenarioRunResponse)
def run_scenario(request: ScenarioRunRequest) -> ScenarioRunResponse:
    try:
        with STATE.lock:
            STATE.latest = engine().run(request.scenario, steps=request.steps)
    except ValueError as exc:
        LOGGER.info("scenario_run_rejected scenario=%r reason=%s", request.scenario, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScenarioRunResponse(
        scenario=STATE.latest.scenario.name,
        telemetry_samples=len(STATE.latest.telemetry),
        anomaly_count=len(STATE.latest.anomalies),
        diagnosis_count=len(STATE.latest.diagnoses),
        decision_statuses=[item.status.value for item in STATE.latest.decisions],
    )


def _latest() -> ScenarioRun:
    with STATE.lock:
        if STATE.latest is None:
            STATE.latest = engine().run("congestion")
        return STATE.latest


@app.get("/telemetry", response_model=list[KPISample])
def telemetry() -> list[KPISample]:
    return _latest().telemetry


@app.get("/anomalies", response_model=list[Anomaly])
def anomalies() -> list[Anomaly]:
    return _latest().anomalies


@app.get("/diagnoses", response_model=list[RootCauseDiagnosis])
def diagnoses() -> list[RootCauseDiagnosis]:
    return _latest().diagnoses


@app.get("/recommendations", response_model=list[CorrectiveAction])
def recommendations() -> list[CorrectiveAction]:
    return _latest().recommendations


@app.get("/decisions", response_model=list[ShadowDecision])
def decisions() -> list[ShadowDecision]:
    return _latest().decisions


@app.post("/actions/validate", response_model=ActionValidationResponse)
def validate_action(request: ActionValidationRequest) -> ActionValidationResponse:
    run = _latest()
    timestamp_samples = [
        sample for sample in run.telemetry if sample.timestamp == request.telemetry_timestamp
    ]
    if not timestamp_samples or request.action.cell_id not in {
        sample.cell_id for sample in timestamp_samples
    }:
        raise HTTPException(
            status_code=422,
            detail="telemetry timestamp and action cell must match stored synthetic telemetry",
        )
    try:
        prediction = TwinSimulator().simulate(
            NetworkTwin(run.topology, timestamp_samples), request.action
        )
    except (ActionSimulationError, ValueError) as exc:
        LOGGER.info(
            "action_validation_rejected action_id=%r cell_id=%r reason=%s",
            request.action.action_id,
            request.action.cell_id,
            exc,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = GuardrailValidator(engine().config.thresholds).validate(
        request.action,
        prediction,
        telemetry_timestamp=request.telemetry_timestamp,
    )
    return ActionValidationResponse(result=result, prediction=prediction)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
