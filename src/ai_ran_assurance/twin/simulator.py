from ai_ran_assurance.domain.enums import ActionType
from ai_ran_assurance.domain.models import CorrectiveAction, TwinPrediction
from ai_ran_assurance.twin.network_twin import NetworkTwin

PREDICTED_KPIS = (
    "prb_utilization_pct",
    "throughput_mbps",
    "rrc_success_pct",
    "handover_success_pct",
    "call_drop_pct",
    "latency_ms",
    "availability_pct",
    "rsrp_dbm",
    "sinr_db",
    "bler_pct",
)


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
    return values


class TwinSimulator:
    """Transparent response factors; not a high-fidelity propagation twin."""

    def simulate(self, twin: NetworkTwin, action: CorrectiveAction) -> TwinPrediction:
        sample = twin.sample(action.cell_id)
        before = {name: float(getattr(sample, name)) for name in PREDICTED_KPIS}
        after = before.copy()
        confidence = 0.82
        match action.action_type:
            case ActionType.RESTORE_NEIGHBOR:
                twin.restore_neighbor(action.cell_id)
                after["handover_success_pct"] += 10
                after["call_drop_pct"] -= 2
                confidence = 0.88
            case ActionType.STEER_TRAFFIC:
                delta = float(action.parameters.get("traffic_delta_pct", 15.0))
                after["prb_utilization_pct"] -= delta
                after["throughput_mbps"] *= 1.12
                after["latency_ms"] -= 12
                after["handover_success_pct"] -= max(0.0, delta - 15) * 0.15
                confidence = 0.76
            case ActionType.ROLLBACK_PARAMETER:
                parameter = str(action.parameters.get("parameter", ""))
                if parameter == "handover_margin_db":
                    after["handover_success_pct"] += 12
                    after["call_drop_pct"] -= 3
                elif parameter == "antenna_tilt_deg":
                    after["rsrp_dbm"] += 12
                    after["sinr_db"] += 4
                    after["call_drop_pct"] -= 1.5
                confidence = 0.8
            case ActionType.ACTIVATE_CAPACITY:
                after["prb_utilization_pct"] -= 22
                after["throughput_mbps"] *= 1.35
                after["latency_ms"] -= 28
                after["rrc_success_pct"] += 3
                confidence = 0.86
            case ActionType.HUMAN_REVIEW:
                confidence = 1.0
        after = {name: round(value, 4) for name, value in _clamp(after).items()}
        return TwinPrediction(
            action_id=action.action_id,
            cell_id=action.cell_id,
            before_kpis=before,
            predicted_kpis=after,
            confidence=confidence,
            model_description=(
                "Deterministic engineering response factors applied to a copied synthetic "
                "network state; no RF propagation or live-network actuation."
            ),
        )
