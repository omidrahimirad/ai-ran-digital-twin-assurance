from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from ai_ran_assurance.domain.models import CorrectiveAction, GuardrailResult, TwinPrediction


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioRunRequest(StrictRequest):
    scenario: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    steps: int | None = Field(default=None, ge=1, le=1000)


class ScenarioRunResponse(BaseModel):
    scenario: str
    telemetry_samples: int
    anomaly_count: int
    diagnosis_count: int
    decision_statuses: list[str]
    synthetic_data: bool = True


class ActionValidationRequest(StrictRequest):
    action: CorrectiveAction
    telemetry_timestamp: AwareDatetime


class ActionValidationResponse(BaseModel):
    result: GuardrailResult
    prediction: TwinPrediction
    shadow_mode: bool = True
