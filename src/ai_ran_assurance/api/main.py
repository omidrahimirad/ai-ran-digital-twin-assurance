import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
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
from ai_ran_assurance.twin import GuardrailValidator
from ai_ran_assurance.workflow import ClosedLoopEngine, ScenarioRun

REQUESTS = Counter("ai_ran_api_requests_total", "API requests", ["path", "method"])
LATENCY = Histogram("ai_ran_api_latency_seconds", "API latency", ["path"])


class AppState:
    engine: ClosedLoopEngine | None = None
    latest: ScenarioRun | None = None


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
    title="AI-Assisted RAN Digital Twin Assurance",
    description="Synthetic-data, simulation-based, shadow-mode engineering prototype.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def observe(request: object, call_next: object) -> Response:
    path = getattr(getattr(request, "url", None), "path", "unknown")
    method = getattr(request, "method", "unknown")
    started = time.perf_counter()
    response = await call_next(request)  # type: ignore[operator]
    REQUESTS.labels(path=path, method=method).inc()
    LATENCY.labels(path=path).observe(time.perf_counter() - started)
    return response  # type: ignore[no-any-return]


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
        STATE.latest = engine().run(request.scenario, steps=request.steps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScenarioRunResponse(
        scenario=STATE.latest.scenario.name,
        telemetry_samples=len(STATE.latest.telemetry),
        anomaly_count=len(STATE.latest.anomalies),
        diagnosis_count=len(STATE.latest.diagnoses),
        decision_statuses=[item.status.value for item in STATE.latest.decisions],
    )


def _latest() -> ScenarioRun:
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
    result = GuardrailValidator(engine().config.thresholds).validate(
        request.action,
        request.prediction,
        telemetry_timestamp=request.telemetry_timestamp,
        evaluated_at=request.evaluated_at,
    )
    return ActionValidationResponse(result=result)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
