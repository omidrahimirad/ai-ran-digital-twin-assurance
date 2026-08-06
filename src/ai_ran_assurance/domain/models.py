import re
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ai_ran_assurance.domain.enums import (
    ActionType,
    AnomalyType,
    DecisionStatus,
    FaultType,
    RootCauseCategory,
)

KPI_FIELDS = frozenset(
    {
        "rsrp_dbm",
        "sinr_db",
        "bler_pct",
        "prb_utilization_pct",
        "throughput_mbps",
        "rrc_success_pct",
        "handover_success_pct",
        "call_drop_pct",
        "latency_ms",
        "availability_pct",
    }
)

FAULT_ROOT_CAUSES = {
    FaultType.CELL_CONGESTION: RootCauseCategory.CONGESTION,
    FaultType.INCREASED_INTERFERENCE: RootCauseCategory.INTERFERENCE,
    FaultType.MISSING_NEIGHBOR: RootCauseCategory.NEIGHBOR_RELATION,
    FaultType.CELL_OUTAGE: RootCauseCategory.CELL_OUTAGE,
    FaultType.TRANSPORT_LATENCY: RootCauseCategory.TRANSPORT,
    FaultType.COVERAGE_DEGRADATION: RootCauseCategory.COVERAGE,
    FaultType.BLER_INCREASE: RootCauseCategory.RADIO_QUALITY,
    FaultType.MOBILITY_MISCONFIGURATION: RootCauseCategory.MOBILITY_CONFIGURATION,
}

FAULT_AFFECTED_KPIS = {
    FaultType.CELL_CONGESTION: {
        "prb_utilization_pct",
        "throughput_mbps",
        "latency_ms",
        "rrc_success_pct",
    },
    FaultType.INCREASED_INTERFERENCE: {
        "sinr_db",
        "bler_pct",
        "throughput_mbps",
        "handover_success_pct",
        "call_drop_pct",
    },
    FaultType.MISSING_NEIGHBOR: {"handover_success_pct", "call_drop_pct"},
    FaultType.CELL_OUTAGE: {
        "availability_pct",
        "rrc_success_pct",
        "handover_success_pct",
        "throughput_mbps",
        "call_drop_pct",
    },
    FaultType.TRANSPORT_LATENCY: {"latency_ms", "throughput_mbps"},
    FaultType.COVERAGE_DEGRADATION: {
        "rsrp_dbm",
        "sinr_db",
        "bler_pct",
        "throughput_mbps",
        "rrc_success_pct",
        "call_drop_pct",
    },
    FaultType.BLER_INCREASE: {"bler_pct", "throughput_mbps", "call_drop_pct"},
    FaultType.MOBILITY_MISCONFIGURATION: {"handover_success_pct", "call_drop_pct"},
}


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class CellConfiguration(DomainModel):
    transmit_power_dbm: float = Field(default=43.0, ge=0, le=80)
    capacity_mbps: float = Field(default=240.0, gt=0, le=100_000)
    handover_margin_db: float = Field(default=3.0, ge=-10, le=15)
    antenna_tilt_deg: float = Field(default=6.0, ge=-10, le=30)


class Cell(DomainModel):
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    capacity_mbps: float = Field(gt=0, le=100_000)
    transmit_power_dbm: float = Field(ge=0, le=80)
    traffic_profile: str = Field(min_length=1, max_length=64)
    configuration: CellConfiguration
    operational: bool = True

    @model_validator(mode="after")
    def validate_configuration_consistency(self) -> "Cell":
        if self.capacity_mbps != self.configuration.capacity_mbps:
            raise ValueError("cell capacity must match its configuration capacity")
        if self.transmit_power_dbm != self.configuration.transmit_power_dbm:
            raise ValueError("cell transmit power must match its configuration")
        return self


class NeighborRelation(DomainModel):
    source_cell: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    target_cell: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    enabled: bool = True

    @model_validator(mode="after")
    def reject_self_relation(self) -> "NeighborRelation":
        if self.source_cell == self.target_cell:
            raise ValueError("a cell cannot be its own neighbor")
        return self


class NetworkTopology(DomainModel):
    cells: list[Cell] = Field(min_length=20)
    neighbor_relations: list[NeighborRelation]

    @model_validator(mode="after")
    def validate_graph_references(self) -> "NetworkTopology":
        cell_ids = [cell.cell_id for cell in self.cells]
        if len(cell_ids) != len(set(cell_ids)):
            raise ValueError("cell identifiers must be unique")
        known = set(cell_ids)
        relation_keys = [
            (relation.source_cell, relation.target_cell) for relation in self.neighbor_relations
        ]
        if len(relation_keys) != len(set(relation_keys)):
            raise ValueError("neighbor relations must be unique")
        unknown = {
            endpoint
            for relation in self.neighbor_relations
            for endpoint in (relation.source_cell, relation.target_cell)
            if endpoint not in known
        }
        if unknown:
            raise ValueError(f"neighbor relations reference unknown cells: {sorted(unknown)}")
        return self


class KPISample(DomainModel):
    timestamp: AwareDatetime
    step: int = Field(ge=0)
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    rsrp_dbm: float = Field(ge=-160, le=-30)
    sinr_db: float = Field(ge=-30, le=50)
    bler_pct: float = Field(ge=0, le=100)
    prb_utilization_pct: float = Field(ge=0, le=100)
    throughput_mbps: float = Field(ge=0, le=100_000)
    rrc_success_pct: float = Field(ge=0, le=100)
    handover_success_pct: float = Field(ge=0, le=100)
    call_drop_pct: float = Field(ge=0, le=100)
    latency_ms: float = Field(ge=0, le=1_000_000)
    availability_pct: float = Field(ge=0, le=100)
    ground_truth: RootCauseCategory = RootCauseCategory.NORMAL


class FaultScenario(DomainModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
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
        expected = FAULT_ROOT_CAUSES[self.fault_type]
        if self.ground_truth is not expected:
            raise ValueError(f"{self.fault_type.value} requires ground truth {expected.value}")
        if len(self.target_cells) != len(set(self.target_cells)):
            raise ValueError("fault target cells must be unique")
        invalid_cells = [
            cell_id
            for cell_id in self.target_cells
            if not re.fullmatch(r"CELL-[0-9]{3,6}", cell_id)
        ]
        if invalid_cells:
            raise ValueError(f"invalid fault target cells: {invalid_cells}")
        unknown_kpis = set(self.affected_kpis) - KPI_FIELDS
        if unknown_kpis:
            raise ValueError(f"unknown affected KPIs: {sorted(unknown_kpis)}")
        if len(self.affected_kpis) != len(set(self.affected_kpis)):
            raise ValueError("affected KPIs must be unique")
        expected_kpis = FAULT_AFFECTED_KPIS[self.fault_type]
        if set(self.affected_kpis) != expected_kpis:
            raise ValueError(
                f"{self.fault_type.value} affected KPIs must be {sorted(expected_kpis)}"
            )
        return self

    def active(self, cell_id: str, step: int) -> bool:
        return cell_id in self.target_cells and self.start_step <= step < (
            self.start_step + self.duration
        )


class Anomaly(DomainModel):
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    timestamp: AwareDatetime
    anomaly_type: AnomalyType
    score: float = Field(ge=0)
    evidence: dict[str, float]
    detector: str


class RootCauseDiagnosis(DomainModel):
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    timestamp: AwareDatetime
    probable_root_cause: RootCauseCategory
    confidence: float = Field(ge=0, le=1)
    evidence_kpis: dict[str, float]
    explanation: str
    next_diagnostic_check: str


class CorrectiveAction(DomainModel):
    action_id: str = Field(min_length=1, max_length=128)
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    action_type: ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    diagnosis_confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=500)
    proposed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_action_parameters(self) -> "CorrectiveAction":
        parameters = self.parameters
        match self.action_type:
            case ActionType.HUMAN_REVIEW:
                expected: set[str] = set()
            case ActionType.ACTIVATE_CAPACITY:
                expected = {"capacity_delta_pct"}
                _finite_number(parameters.get("capacity_delta_pct"), "capacity_delta_pct", 0, 100)
            case ActionType.STEER_TRAFFIC:
                expected = {"target_cell", "traffic_delta_pct"}
                _cell_parameter(parameters.get("target_cell"), "target_cell", self.cell_id)
                _finite_number(parameters.get("traffic_delta_pct"), "traffic_delta_pct", 0, 50)
            case ActionType.RESTORE_NEIGHBOR:
                expected = {"target_cell"}
                _cell_parameter(parameters.get("target_cell"), "target_cell", self.cell_id)
            case ActionType.ROLLBACK_PARAMETER:
                expected = {"parameter", "current_value", "previous_value"}
                if parameters.get("parameter") not in {
                    "handover_margin_db",
                    "antenna_tilt_deg",
                }:
                    raise ValueError("rollback parameter is not supported")
                _finite_number(parameters.get("current_value"), "current_value", -20, 100)
                _finite_number(parameters.get("previous_value"), "previous_value", -20, 100)
        if set(parameters) != expected:
            raise ValueError(
                f"{self.action_type.value} parameters must be exactly {sorted(expected)}"
            )
        return self


class TwinPrediction(DomainModel):
    action_id: str = Field(min_length=1, max_length=128)
    cell_id: str = Field(pattern=r"^CELL-[0-9]{3,6}$")
    before_kpis: dict[str, float]
    predicted_kpis: dict[str, float]
    impacted_cell_before_kpis: dict[str, dict[str, float]] = Field(default_factory=dict)
    impacted_cell_kpis: dict[str, dict[str, float]] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    model_description: str = Field(min_length=1, max_length=500)
    assumptions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_kpi_vectors(self) -> "TwinPrediction":
        _validate_kpi_vector(self.before_kpis, "before_kpis")
        _validate_kpi_vector(self.predicted_kpis, "predicted_kpis")
        if set(self.impacted_cell_before_kpis) != set(self.impacted_cell_kpis):
            raise ValueError("impacted before/after cells must match")
        if self.cell_id in self.impacted_cell_kpis:
            raise ValueError("the primary cell cannot also be an impacted cell")
        for cell_id, values in self.impacted_cell_before_kpis.items():
            if not re.fullmatch(r"CELL-[0-9]{3,6}", cell_id):
                raise ValueError(f"invalid impacted cell identifier {cell_id!r}")
            _validate_kpi_vector(values, f"impacted_cell_before_kpis[{cell_id}]")
            _validate_kpi_vector(self.impacted_cell_kpis[cell_id], f"impacted_cell_kpis[{cell_id}]")
        return self


class GuardrailResult(DomainModel):
    approved: bool
    violations: list[str]
    evaluated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_outcome(self) -> "GuardrailResult":
        if self.approved == bool(self.violations):
            raise ValueError("approved must be true exactly when violations are empty")
        return self


class ShadowDecision(DomainModel):
    action: CorrectiveAction
    prediction: TwinPrediction
    guardrail: GuardrailResult
    status: DecisionStatus
    note: str

    @model_validator(mode="after")
    def validate_consistency(self) -> "ShadowDecision":
        if self.action.action_id != self.prediction.action_id:
            raise ValueError("action and prediction identifiers must match")
        if self.action.cell_id != self.prediction.cell_id:
            raise ValueError("action and prediction cells must match")
        expected = (
            DecisionStatus.HUMAN_REVIEW
            if self.action.action_type is ActionType.HUMAN_REVIEW
            else (
                DecisionStatus.SHADOW_APPROVED
                if self.guardrail.approved
                else DecisionStatus.SHADOW_REJECTED
            )
        )
        if self.status is not expected:
            raise ValueError("shadow decision status is inconsistent with guardrails")
        return self


def _finite_number(value: Any, name: str, lower_exclusive: float, upper_inclusive: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    numeric = float(value)
    if not lower_exclusive < numeric <= upper_inclusive:
        raise ValueError(
            f"{name} must be greater than {lower_exclusive} and at most {upper_inclusive}"
        )
    return numeric


def _cell_parameter(value: Any, name: str, source_cell: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"CELL-[0-9]{3,6}", value):
        raise ValueError(f"{name} must be a valid cell identifier")
    if value == source_cell:
        raise ValueError(f"{name} must differ from the source cell")
    return value


def _validate_kpi_vector(values: dict[str, float], name: str) -> None:
    if set(values) != KPI_FIELDS:
        missing = sorted(KPI_FIELDS - set(values))
        extra = sorted(set(values) - KPI_FIELDS)
        raise ValueError(f"{name} has missing KPIs {missing} and extra KPIs {extra}")
