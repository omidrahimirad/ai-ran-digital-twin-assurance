from dataclasses import dataclass

from ai_ran_assurance.config import ThresholdSettings
from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.domain.models import Anomaly, KPISample, RootCauseDiagnosis


@dataclass(frozen=True)
class DiagnosisRule:
    category: RootCauseCategory
    confidence: float
    explanation: str
    next_check: str


class RootCauseEngine:
    """Explainable KPI-pattern mapping with no vendor-specific counters."""

    def __init__(self, settings: ThresholdSettings) -> None:
        self.settings = settings

    def _match(self, sample: KPISample) -> DiagnosisRule:
        policy = self.settings
        if (
            sample.availability_pct < policy.availability_min_pct - 19
            and sample.rrc_success_pct < policy.rrc_success_min_pct - 25
            and sample.throughput_mbps < 50
        ):
            return DiagnosisRule(
                RootCauseCategory.CELL_OUTAGE,
                0.9,
                "Availability, access success, and user throughput collapsed together.",
                "Verify simulated cell operational state and upstream power/alarm evidence.",
            )
        if (
            sample.prb_utilization_pct > policy.prb_utilization_max_pct - 5
            and sample.latency_ms > 25
        ):
            return DiagnosisRule(
                RootCauseCategory.CONGESTION,
                0.72,
                "High resource use coincides with latency growth and throughput pressure.",
                "Compare offered traffic with configured cell capacity and neighbor headroom.",
            )
        if (
            sample.sinr_db < policy.sinr_min_db + 3
            and sample.bler_pct > policy.bler_max_pct - 4
            and sample.rsrp_dbm > policy.rsrp_min_dbm + 5
        ):
            return DiagnosisRule(
                RootCauseCategory.INTERFERENCE,
                0.74,
                "Low SINR and elevated BLER jointly indicate interference-like degradation.",
                "Inspect neighbor overlap and the synthetic interference contribution.",
            )
        if sample.rsrp_dbm < policy.rsrp_min_dbm + 7 and sample.sinr_db < policy.sinr_min_db + 7:
            return DiagnosisRule(
                RootCauseCategory.COVERAGE,
                0.72,
                "RSRP and SINR degraded together while the cell remained available.",
                "Review transmit power, antenna settings, and simulated coverage assumptions.",
            )
        if (
            sample.latency_ms > policy.latency_max_ms
            and sample.prb_utilization_pct < policy.prb_utilization_max_pct
        ):
            return DiagnosisRule(
                RootCauseCategory.TRANSPORT,
                0.82,
                "Latency rose beyond the safety limit without radio-resource saturation.",
                "Check transport path delay, loss, and queue telemetry in the synthetic model.",
            )
        if sample.bler_pct > policy.bler_max_pct:
            return DiagnosisRule(
                RootCauseCategory.RADIO_QUALITY,
                0.76,
                "BLER increased without the combined low-SINR interference signature.",
                "Compare modulation/coding assumptions and radio-quality measurements.",
            )
        if (
            sample.handover_success_pct < policy.handover_success_min_pct
            and sample.call_drop_pct > policy.call_drop_max_pct
        ):
            return DiagnosisRule(
                RootCauseCategory.UNKNOWN,
                0.35,
                "The mobility signature cannot distinguish a missing neighbor relation from "
                "parameter misconfiguration without topology or configuration-change evidence.",
                "Audit bidirectional neighbor state and compare mobility parameters with a "
                "known-good configuration before proposing a change.",
            )
        return DiagnosisRule(
            RootCauseCategory.UNKNOWN,
            0.3,
            "The anomaly does not match a sufficiently specific synthetic KPI signature.",
            "Request human review and correlate additional topology and alarm evidence.",
        )

    def diagnose(self, anomaly: Anomaly, sample: KPISample) -> RootCauseDiagnosis:
        if anomaly.cell_id != sample.cell_id or anomaly.timestamp != sample.timestamp:
            raise ValueError("anomaly and KPI sample must refer to the same cell and timestamp")
        rule = self._match(sample)
        return RootCauseDiagnosis(
            cell_id=sample.cell_id,
            timestamp=sample.timestamp,
            probable_root_cause=rule.category,
            confidence=rule.confidence,
            evidence_kpis={
                name: value
                for name, value in anomaly.evidence.items()
                if name
                in {
                    "availability_pct",
                    "rrc_success_pct",
                    "prb_utilization_pct",
                    "throughput_mbps",
                    "latency_ms",
                    "sinr_db",
                    "bler_pct",
                    "rsrp_dbm",
                    "handover_success_pct",
                    "call_drop_pct",
                }
            },
            explanation=rule.explanation,
            next_diagnostic_check=rule.next_check,
        )
