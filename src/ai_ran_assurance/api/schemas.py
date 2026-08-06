from datetime import datetime

from pydantic import BaseModel, Field

from ai_ran_assurance.domain.models import CorrectiveAction, GuardrailResult, TwinPrediction


class ScenarioRunRequest(BaseModel):
    scenario: str
    steps: int | None = Field(default=None, ge=1, le=1000)


class ScenarioRunResponse(BaseModel):
    scenario: str
    telemetry_samples: int
    anomaly_count: int
    diagnosis_count: int
    decision_statuses: list[str]
    synthetic_data: bool = True


class ActionValidationRequest(BaseModel):
    action: CorrectiveAction
    prediction: TwinPrediction
    telemetry_timestamp: datetime
    evaluated_at: datetime | None = None


class ActionValidationResponse(BaseModel):
    result: GuardrailResult
    shadow_mode: bool = True
