from ai_ran_assurance.domain.enums import ActionType
from ai_ran_assurance.domain.models import KPI_FIELDS, CorrectiveAction, TwinPrediction
from ai_ran_assurance.twin.network_twin import NetworkTwin

PREDICTED_KPIS = tuple(sorted(KPI_FIELDS))


class ActionSimulationError(ValueError):
    """Raised when copied state cannot support a requested what-if action."""


def _clamp(values: dict[str, float]) -> dict[str, float]:
    for name in (
        "prb_utilization_pct",
        "rrc_success_pct",
        "handover_success_pct",
        "call_drop_pct",
        "availability_pct",
        "bler_pct",
    ):
        values[name] = min(100.0, max(0.0, values[name]))
    values["throughput_mbps"] = max(0.0, values["throughput_mbps"])
    values["latency_ms"] = max(0.0, values["latency_ms"])
    values["rsrp_dbm"] = min(-30.0, max(-160.0, values["rsrp_dbm"]))
    values["sinr_db"] = min(50.0, max(-30.0, values["sinr_db"]))
    return values


def _vector(twin: NetworkTwin, cell_id: str) -> dict[str, float]:
    sample = twin.sample(cell_id)
    return {name: float(getattr(sample, name)) for name in PREDICTED_KPIS}


def _rounded(values: dict[str, float]) -> dict[str, float]:
    return {name: round(value, 4) for name, value in _clamp(values).items()}


class TwinSimulator:
    """Bounded state-and-response surrogate, not a predictive network twin."""

    def simulate(self, twin: NetworkTwin, action: CorrectiveAction) -> TwinPrediction:
        before = _vector(twin, action.cell_id)
        after = before.copy()
        impacted_before: dict[str, dict[str, float]] = {}
        impacted_after: dict[str, dict[str, float]] = {}
        assumptions: list[str]
        confidence: float
        match action.action_type:
            case ActionType.RESTORE_NEIGHBOR:
                target = str(action.parameters["target_cell"])
                twin.restore_neighbor(action.cell_id, target)
                after["handover_success_pct"] += 2.0
                after["call_drop_pct"] -= 0.35
                confidence = 0.58
                assumptions = [
                    "The specified disabled relation is the material cause of mobility failures.",
                    "The target cell is reachable and has adequate mobility capacity.",
                ]
            case ActionType.STEER_TRAFFIC:
                target = str(action.parameters["target_cell"])
                if target not in twin.neighbors(action.cell_id):
                    raise ActionSimulationError("traffic target is not an enabled neighbor")
                target_before = _vector(twin, target)
                if target_before["availability_pct"] < 99:
                    raise ActionSimulationError("traffic target is not sufficiently available")
                fraction = float(action.parameters["traffic_delta_pct"]) / 100
                source_transfer_prb = before["prb_utilization_pct"] * fraction
                source_capacity = float(twin.cell_configuration(action.cell_id).capacity_mbps)
                target_capacity = float(twin.cell_configuration(target).capacity_mbps)
                target_transfer_prb = source_transfer_prb * source_capacity / target_capacity
                if target_before["prb_utilization_pct"] + target_transfer_prb > 95:
                    raise ActionSimulationError("traffic target lacks modeled PRB headroom")
                after["prb_utilization_pct"] -= source_transfer_prb
                after["throughput_mbps"] *= 1 - fraction
                after["latency_ms"] -= 0.15 * source_transfer_prb
                after["handover_success_pct"] -= 0.3
                target_after = target_before.copy()
                target_after["prb_utilization_pct"] += target_transfer_prb
                target_after["throughput_mbps"] += before["throughput_mbps"] * fraction
                target_after["latency_ms"] += 0.2 * target_transfer_prb
                impacted_before[target] = target_before
                impacted_after[target] = _rounded(target_after)
                confidence = 0.52
                assumptions = [
                    "PRB demand transfers proportionally between source and target capacity.",
                    "Radio conditions and user demand remain unchanged during steering.",
                ]
            case ActionType.ROLLBACK_PARAMETER:
                parameter = str(action.parameters["parameter"])
                current = float(action.parameters["current_value"])
                previous = float(action.parameters["previous_value"])
                configured = float(getattr(twin.cell_configuration(action.cell_id), parameter))
                if abs(configured - current) > 1e-6:
                    raise ActionSimulationError(
                        "rollback current_value does not match copied cell configuration"
                    )
                delta = previous - current
                if parameter == "handover_margin_db":
                    after["handover_success_pct"] += min(1.5, abs(delta) * 0.5)
                    after["call_drop_pct"] -= min(0.3, abs(delta) * 0.1)
                else:
                    after["rsrp_dbm"] -= 0.7 * delta
                    after["sinr_db"] -= 0.2 * delta
                confidence = 0.45
                assumptions = [
                    "The previous value is known-good and other configuration is unchanged.",
                    "The local linear response excludes propagation and mobility coupling.",
                ]
            case ActionType.ACTIVATE_CAPACITY:
                delta = float(action.parameters["capacity_delta_pct"]) / 100
                old_prb = before["prb_utilization_pct"]
                new_prb = old_prb / (1 + delta)
                old_queue = max(0.0, old_prb - 75)
                new_queue = max(0.0, new_prb - 75)
                after["prb_utilization_pct"] = new_prb
                after["latency_ms"] -= 0.045 * (old_queue**2 - new_queue**2)
                after["rrc_success_pct"] += 0.03 * (old_prb - new_prb)
                if old_prb > 90:
                    after["throughput_mbps"] *= 1 + min(0.08, delta * 0.25)
                confidence = 0.64
                assumptions = [
                    "Additional capacity is immediately usable by the same offered traffic.",
                    "The response excludes scheduler, energy, and transport constraints.",
                ]
            case ActionType.HUMAN_REVIEW:
                confidence = 0.0
                assumptions = ["No KPI change is predicted because no action is simulated."]
        return TwinPrediction(
            action_id=action.action_id,
            cell_id=action.cell_id,
            before_kpis=before,
            predicted_kpis=_rounded(after),
            impacted_cell_before_kpis=impacted_before,
            impacted_cell_kpis=impacted_after,
            confidence=confidence,
            model_description=(
                "Bounded deterministic response surrogate applied to copied synthetic state; "
                "not a calibrated causal model, RF model, or live-network prediction."
            ),
            assumptions=assumptions,
        )
