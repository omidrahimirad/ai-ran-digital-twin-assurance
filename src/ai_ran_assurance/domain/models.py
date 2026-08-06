from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_ran_assurance.domain.enums import (
    ActionType,
    AnomalyType,
    DecisionStatus,
    FaultType,
    RootCauseCategory,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CellConfiguration(DomainModel):
    transmit_power_dbm: float = 43.0
    capacity_mbps: float = Field(default=240.0, gt=0)
    handover_margin_db: float = 3.0
    antenna_tilt_deg: float = 6.0


class Cell(DomainModel):
    cell_id: str
    capacity_mbps: float = Field(gt=0)
    transmit_power_dbm: float
    traffic_profile: str
    configuration: CellConfiguration
    operational: bool = True


class NeighborRelation(DomainModel):
    source_cell: str
    target_cell: str
    enabled: bool = True


class NetworkTopology(DomainModel):
    cells: list[Cell]
    neighbor_relations: list[NeighborRelation]


class KPISample(DomainModel):
    timestamp: datetime
    step: int = Field(ge=0)
    cell_id: str
    rsrp_dbm: float
    sinr_db: float
    bler_pct: float = Field(ge=0, le=100)
    prb_utilization_pct: float = Field(ge=0, le=100)
    throughput_mbps: float = Field(ge=0)
    rrc_success_pct: float = Field(ge=0, le=100)
    handover_success_pct: float = Field(ge=0, le=100)
    call_drop_pct: float = Field(ge=0, le=100)
    latency_ms: float = Field(ge=0)
    availability_pct: float = Field(ge=0, le=100)
    ground_truth: RootCauseCategory = RootCauseCategory.NORMAL


class FaultScenario(DomainModel):
    name: str
    fault_type: FaultType
    target_cells: list[str] = Field(min_length=1)
    start_step: int = Field(ge=0)
    duration: int = Field(gt=0)
    severity: float = Field(gt=0, le=1)
    affected_kpis: list[str] = Field(min_length=1)
    ground_truth: RootCauseCategory

    @model_validator(mode="after")
    def validate_truth(self) -> "FaultScenario":
        if self.ground_truth is RootCauseCategory.NORMAL:
            raise ValueError("fault scenarios cannot use normal ground truth")
        return self

    def active(self, cell_id: str, step: int) -> bool:
        return cell_id in self.target_cells and self.start_step <= step < (
            self.start_step + self.duration
        )


class Anomaly(DomainModel):
    cell_id: str
    timestamp: datetime
    anomaly_type: AnomalyType
    score: float = Field(ge=0)
    evidence: dict[str, float]
    detector: str


class RootCauseDiagnosis(DomainModel):
    cell_id: str
    timestamp: datetime
    probable_root_cause: RootCauseCategory
    confidence: float = Field(ge=0, le=1)
    evidence_kpis: dict[str, float]
    explanation: str
    next_diagnostic_check: str


class CorrectiveAction(DomainModel):
    action_id: str
    cell_id: str
    action_type: ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    proposed_at: datetime


class TwinPrediction(DomainModel):
    action_id: str
    cell_id: str
    before_kpis: dict[str, float]
    predicted_kpis: dict[str, float]
    confidence: float = Field(ge=0, le=1)
    model_description: str


class GuardrailResult(DomainModel):
    approved: bool
    violations: list[str]
    evaluated_at: datetime


class ShadowDecision(DomainModel):
    action: CorrectiveAction
    prediction: TwinPrediction
    guardrail: GuardrailResult
    status: DecisionStatus
    note: str
