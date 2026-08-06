from collections.abc import MutableMapping

from ai_ran_assurance.domain.enums import FaultType
from ai_ran_assurance.domain.models import FaultScenario


class FaultInjector:
    """Apply transparent deterministic KPI effects for configured synthetic faults."""

    def apply(
        self,
        values: MutableMapping[str, float],
        scenario: FaultScenario | None,
        cell_id: str,
        step: int,
        *,
        capacity_mbps: float,
    ) -> bool:
        if scenario is None or not scenario.active(cell_id, step):
            return False
        severity = scenario.severity
        match scenario.fault_type:
            case FaultType.CELL_CONGESTION:
                values["prb_utilization_pct"] += 35 * severity
                queue_pressure = max(0.0, values["prb_utilization_pct"] - 80)
                values["latency_ms"] += 1.4 * queue_pressure
                values["throughput_mbps"] *= 1 - 0.18 * severity
                values["rrc_success_pct"] -= 0.08 * queue_pressure
            case FaultType.INCREASED_INTERFERENCE:
                previous_bler = values["bler_pct"]
                values["sinr_db"] -= 16 * severity
                values["bler_pct"] += 14 * severity
                values["throughput_mbps"] *= max(
                    0.35, 1 - 0.025 * (values["bler_pct"] - previous_bler) - 0.1 * severity
                )
                values["handover_success_pct"] -= max(0, 5 - values["sinr_db"]) * 0.2
                values["call_drop_pct"] += 0.05 * (values["bler_pct"] - previous_bler)
            case FaultType.MISSING_NEIGHBOR:
                values["handover_success_pct"] -= 10 * severity
                values["call_drop_pct"] += 2.5 * severity
            case FaultType.CELL_OUTAGE:
                values["availability_pct"] = max(0.0, 100 * (1 - severity))
                values["rrc_success_pct"] *= 1 - severity
                values["handover_success_pct"] *= 1 - 0.8 * severity
                values["throughput_mbps"] *= 1 - severity
                values["call_drop_pct"] += 40 * severity
            case FaultType.TRANSPORT_LATENCY:
                values["latency_ms"] += 75 * severity
                values["throughput_mbps"] *= 1 - 0.08 * severity
            case FaultType.COVERAGE_DEGRADATION:
                values["rsrp_dbm"] -= 30 * severity
                values["sinr_db"] -= 12 * severity
                values["bler_pct"] += 8 * severity
                values["throughput_mbps"] *= 1 - 0.22 * severity
                values["rrc_success_pct"] -= 2 * severity
                values["call_drop_pct"] += 2.2 * severity
            case FaultType.BLER_INCREASE:
                values["bler_pct"] += 16 * severity
                values["throughput_mbps"] *= 1 - 0.3 * severity
                values["call_drop_pct"] += 0.08 * 16 * severity
            case FaultType.MOBILITY_MISCONFIGURATION:
                values["handover_success_pct"] -= 9 * severity
                values["call_drop_pct"] += 2.8 * severity
        values["throughput_mbps"] = min(values["throughput_mbps"], capacity_mbps)
        return True
