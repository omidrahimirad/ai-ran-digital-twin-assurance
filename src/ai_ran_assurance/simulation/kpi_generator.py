from datetime import UTC, datetime, timedelta

import numpy as np

from ai_ran_assurance.config import NetworkSettings
from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.domain.models import KPI_FIELDS, FaultScenario, KPISample, NetworkTopology
from ai_ran_assurance.simulation.fault_injector import FaultInjector

KPI_NAMES = tuple(sorted(KPI_FIELDS))


def _bounded(values: dict[str, float]) -> dict[str, float]:
    for name in (
        "bler_pct",
        "prb_utilization_pct",
        "rrc_success_pct",
        "handover_success_pct",
        "call_drop_pct",
        "availability_pct",
    ):
        values[name] = float(np.clip(values[name], 0, 100))
    values["throughput_mbps"] = max(0.0, values["throughput_mbps"])
    values["latency_ms"] = max(0.0, values["latency_ms"])
    return values


class KPIGenerator:
    """Correlated KPI generator; an engineering abstraction, not an RF simulator."""

    def __init__(self, topology: NetworkTopology, settings: NetworkSettings) -> None:
        self.topology = topology
        self.settings = settings
        self.injector = FaultInjector()

    def generate(
        self,
        steps: int,
        scenario: FaultScenario | None = None,
        *,
        start: datetime | None = None,
        seed: int | None = None,
    ) -> list[KPISample]:
        if steps <= 0:
            raise ValueError("steps must be positive")
        rng = np.random.default_rng(self.settings.seed if seed is None else seed)
        start_time = start or datetime(2026, 1, 1, tzinfo=UTC)
        if start_time.tzinfo is None or start_time.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        samples: list[KPISample] = []
        cell_count = len(self.topology.cells)
        shadowing = rng.normal(0, 2.2, cell_count)
        traffic_bias = rng.normal(0, 0.025, cell_count)
        load_state = np.zeros(cell_count)
        signal_state = np.zeros(cell_count)
        interference_state = np.zeros(cell_count)
        for step in range(steps):
            hour = (
                start_time.hour
                + start_time.minute / 60
                + step * self.settings.interval_minutes / 60
            ) % 24
            morning_peak = np.exp(-(((hour - 8) / 2.8) ** 2))
            evening_peak = np.exp(-(((hour - 18) / 3.8) ** 2))
            traffic_shape = float(min(1.0, 0.20 + 0.25 * morning_peak + 0.60 * evening_peak))
            for index, cell in enumerate(self.topology.cells):
                load_state[index] = 0.78 * load_state[index] + rng.normal(0, 1.1)
                signal_state[index] = 0.92 * signal_state[index] + rng.normal(0, 0.3)
                interference_state[index] = 0.72 * interference_state[index] + rng.normal(0, 0.18)
                offered_ratio = float(
                    np.clip(
                        0.12 + 0.58 * traffic_shape + traffic_bias[index] + load_state[index] / 100,
                        0.10,
                        0.78,
                    )
                )
                rsrp = -85 + (cell.transmit_power_dbm - 43) + shadowing[index] + signal_state[index]
                offered_mbps = cell.capacity_mbps * offered_ratio
                interference_penalty = 2.2 + 4.5 * offered_ratio + interference_state[index]
                sinr = 22 + 0.32 * (rsrp + 85) - interference_penalty
                bler = 0.4 + 20 / (1 + np.exp((sinr - 3) / 2.5))
                radio_efficiency = float(np.clip((sinr + 5) / 25, 0.08, 1.0))
                achievable_mbps = cell.capacity_mbps * radio_efficiency * (1 - bler / 100)
                prb = float(np.clip(100 * offered_mbps / max(achievable_mbps, 1), 1, 100))
                throughput = min(offered_mbps, achievable_mbps)
                queue_pressure = max(0.0, prb - 75)
                latency = 10 + 0.18 * prb + 0.045 * queue_pressure**2 + 0.5 * bler
                availability = 99.995 - abs(rng.normal(0, 0.0025))
                rrc = 99.75 - 0.055 * max(0, prb - 80) - 0.035 * bler
                handover = 99.35 - 0.22 * max(0, 5 - sinr) + rng.normal(0, 0.05)
                call_drop = 0.18 + 0.04 * bler + 0.12 * max(0, 97 - handover)
                values = {
                    "rsrp_dbm": float(rsrp),
                    "sinr_db": float(sinr),
                    "bler_pct": float(bler),
                    "prb_utilization_pct": prb,
                    "throughput_mbps": float(throughput),
                    "rrc_success_pct": float(rrc),
                    "handover_success_pct": float(handover),
                    "call_drop_pct": float(call_drop),
                    "latency_ms": float(latency),
                    "availability_pct": float(availability),
                }
                active = self.injector.apply(
                    values,
                    scenario,
                    cell.cell_id,
                    step,
                    capacity_mbps=cell.capacity_mbps,
                )
                values = _bounded(values)
                samples.append(
                    KPISample(
                        timestamp=start_time
                        + timedelta(minutes=step * self.settings.interval_minutes),
                        step=step,
                        cell_id=cell.cell_id,
                        ground_truth=(
                            scenario.ground_truth
                            if active and scenario is not None
                            else RootCauseCategory.NORMAL
                        ),
                        **{name: round(values[name], 4) for name in KPI_NAMES},
                    )
                )
        return samples
