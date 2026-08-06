from collections import defaultdict

import numpy as np

from ai_ran_assurance.config import ThresholdSettings
from ai_ran_assurance.domain.enums import AnomalyType
from ai_ran_assurance.domain.models import Anomaly, KPISample
from ai_ran_assurance.simulation.kpi_generator import KPI_NAMES


class RuleDetector:
    """Configurable thresholds plus past-only rolling Z-scores."""

    name = "rule_and_rolling_zscore"

    def __init__(self, settings: ThresholdSettings) -> None:
        self.settings = settings

    def _threshold_evidence(self, sample: KPISample) -> dict[str, float]:
        checks = {
            "rsrp_dbm": sample.rsrp_dbm < self.settings.rsrp_min_dbm,
            "sinr_db": sample.sinr_db < self.settings.sinr_min_db,
            "bler_pct": sample.bler_pct > self.settings.bler_max_pct,
            "prb_utilization_pct": (
                sample.prb_utilization_pct > self.settings.prb_utilization_max_pct
            ),
            "throughput_mbps": sample.throughput_mbps < self.settings.throughput_min_mbps,
            "rrc_success_pct": sample.rrc_success_pct < self.settings.rrc_success_min_pct,
            "handover_success_pct": (
                sample.handover_success_pct < self.settings.handover_success_min_pct
            ),
            "call_drop_pct": sample.call_drop_pct > self.settings.call_drop_max_pct,
            "latency_ms": sample.latency_ms > self.settings.latency_max_ms,
            "availability_pct": sample.availability_pct < self.settings.availability_min_pct,
        }
        return {name: float(getattr(sample, name)) for name, violated in checks.items() if violated}

    def detect(self, samples: list[KPISample]) -> list[Anomaly]:
        history: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        anomalies: list[Anomaly] = []
        for sample in sorted(samples, key=lambda item: (item.timestamp, item.cell_id)):
            evidence = self._threshold_evidence(sample)
            zscores: list[float] = []
            for name in KPI_NAMES:
                values = history[sample.cell_id][name][-self.settings.rolling_window :]
                value = float(getattr(sample, name))
                if len(values) >= self.settings.rolling_window:
                    standard_deviation = float(np.std(values))
                    if standard_deviation > 0.05:
                        zscore = abs((value - float(np.mean(values))) / standard_deviation)
                        if zscore > self.settings.zscore_limit:
                            evidence.setdefault(name, value)
                            zscores.append(zscore)
                history[sample.cell_id][name].append(value)
            if evidence:
                anomaly_type = (
                    AnomalyType.THRESHOLD
                    if self._threshold_evidence(sample)
                    else AnomalyType.STATISTICAL
                )
                anomalies.append(
                    Anomaly(
                        cell_id=sample.cell_id,
                        timestamp=sample.timestamp,
                        anomaly_type=anomaly_type,
                        score=round(max([1.0, *zscores]), 4),
                        evidence=evidence,
                        detector=self.name,
                    )
                )
        return anomalies
