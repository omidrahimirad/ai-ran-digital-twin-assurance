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
    ) -> bool:
        if scenario is None or not scenario.active(cell_id, step):
            return False
        severity = scenario.severity
        match scenario.fault_type:
            case FaultType.CELL_CONGESTION:
                values["prb_utilization_pct"] += 35 * severity
                values["latency_ms"] += 55 * severity
                values["throughput_mbps"] *= 1 - 0.55 * severity
                values["rrc_success_pct"] -= 5 * severity
            case FaultType.INCREASED_INTERFERENCE:
                values["sinr_db"] -= 14 * severity
                values["bler_pct"] += 18 * severity
                values["throughput_mbps"] *= 1 - 0.5 * severity
            case FaultType.MISSING_NEIGHBOR:
                values["handover_success_pct"] -= 16 * severity
                values["call_drop_pct"] += 4 * severity
            case FaultType.CELL_OUTAGE:
                values["availability_pct"] = max(0.0, 100 * (1 - severity))
                values["rrc_success_pct"] *= 1 - severity
                values["handover_success_pct"] *= 1 - 0.8 * severity
                values["throughput_mbps"] *= 1 - severity
                values["call_drop_pct"] += 40 * severity
            case FaultType.TRANSPORT_LATENCY:
                values["latency_ms"] += 120 * severity
                values["throughput_mbps"] *= 1 - 0.35 * severity
            case FaultType.COVERAGE_DEGRADATION:
                values["rsrp_dbm"] -= 20 * severity
                values["sinr_db"] -= 7 * severity
                values["call_drop_pct"] += 3 * severity
            case FaultType.BLER_INCREASE:
                values["bler_pct"] += 25 * severity
                values["throughput_mbps"] *= 1 - 0.5 * severity
            case FaultType.MOBILITY_MISCONFIGURATION:
                values["handover_success_pct"] -= 20 * severity
                values["call_drop_pct"] += 5 * severity
                values["latency_ms"] += 10 * severity
        return True
