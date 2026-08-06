from datetime import UTC, datetime, timedelta

import numpy as np

from ai_ran_assurance.config import NetworkSettings
from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.domain.models import FaultScenario, KPISample, NetworkTopology
from ai_ran_assurance.simulation.fault_injector import FaultInjector

KPI_NAMES = (
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
)


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
        samples: list[KPISample] = []
        for step in range(steps):
            hour = (step * self.settings.interval_minutes / 60) % 24
            daily_wave = (np.sin((hour - 7) * np.pi / 12) + 1) / 2
            for index, cell in enumerate(self.topology.cells):
                local_wave = float(np.clip(daily_wave + 0.05 * np.sin(index), 0, 1))
                load = float(np.clip(28 + 55 * local_wave + rng.normal(0, 2.0), 8, 92))
                rsrp = -82 - 0.55 * (index % 8) + rng.normal(0, 1.2)
                interference = 1.8 + load * 0.035 + rng.normal(0, 0.25)
                sinr = 24 + (rsrp + 82) * 0.3 - interference + rng.normal(0, 0.6)
                bler = max(0.2, 1.2 + 0.32 * max(0, 14 - sinr) + rng.normal(0, 0.25))
                spectral_factor = float(np.clip((sinr + 5) / 28, 0.08, 1))
                congestion_factor = float(np.clip(1 - max(0, load - 70) / 85, 0.25, 1))
                throughput = (
                    cell.capacity_mbps
                    * spectral_factor
                    * congestion_factor
                    * (1 - bler / 100)
                    * 0.72
                )
                availability = 99.99 - max(0, rng.normal(0, 0.015))
                rrc = 99.65 - max(0, load - 78) * 0.08 - (100 - availability) * 0.2
                handover = 99.25 - interference * 0.08 + rng.normal(0, 0.08)
                call_drop = 0.25 + bler * 0.025 + max(0, 96 - handover) * 0.12
                latency = 12 + load * 0.24 + bler * 0.5 + rng.normal(0, 0.8)
                values = {
                    "rsrp_dbm": float(rsrp),
                    "sinr_db": float(sinr),
                    "bler_pct": float(bler),
                    "prb_utilization_pct": load,
                    "throughput_mbps": float(throughput),
                    "rrc_success_pct": float(rrc),
                    "handover_success_pct": float(handover),
                    "call_drop_pct": float(call_drop),
                    "latency_ms": float(latency),
                    "availability_pct": float(availability),
                }
                active = self.injector.apply(values, scenario, cell.cell_id, step)
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
