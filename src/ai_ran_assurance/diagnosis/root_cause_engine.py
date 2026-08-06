from dataclasses import dataclass

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

    def _match(self, sample: KPISample) -> DiagnosisRule:
        if sample.availability_pct < 99 or sample.rrc_success_pct < 50:
            return DiagnosisRule(
                RootCauseCategory.CELL_OUTAGE,
                0.98,
                "Availability, access success, and user throughput collapsed together.",
                "Verify simulated cell operational state and upstream power/alarm evidence.",
            )
        if sample.prb_utilization_pct > 90 and sample.latency_ms > 55:
            return DiagnosisRule(
                RootCauseCategory.CONGESTION,
                0.92,
                "High resource use coincides with latency growth and throughput pressure.",
                "Compare offered traffic with configured cell capacity and neighbor headroom.",
            )
        if sample.sinr_db < 8 and sample.bler_pct > 12:
            return DiagnosisRule(
                RootCauseCategory.INTERFERENCE,
                0.9,
                "Low SINR and elevated BLER jointly indicate interference-like degradation.",
                "Inspect neighbor overlap and the synthetic interference contribution.",
            )
        if sample.rsrp_dbm < -100 and sample.sinr_db < 15:
            return DiagnosisRule(
                RootCauseCategory.COVERAGE,
                0.9,
                "RSRP and SINR degraded together while the cell remained available.",
                "Review transmit power, antenna settings, and simulated coverage assumptions.",
            )
        if sample.latency_ms > 80 and sample.prb_utilization_pct < 90:
            return DiagnosisRule(
                RootCauseCategory.TRANSPORT,
                0.9,
                "Latency rose beyond the safety limit without radio-resource saturation.",
                "Check transport path delay, loss, and queue telemetry in the synthetic model.",
            )
        if sample.bler_pct > 12:
            return DiagnosisRule(
                RootCauseCategory.RADIO_QUALITY,
                0.86,
                "BLER increased without the combined low-SINR interference signature.",
                "Compare modulation/coding assumptions and radio-quality measurements.",
            )
        if sample.handover_success_pct < 85 or (
            sample.handover_success_pct < 94 and sample.latency_ms > 35
        ):
            return DiagnosisRule(
                RootCauseCategory.MOBILITY_CONFIGURATION,
                0.84,
                "Severe handover degradation and drop growth suggest mobility tuning drift.",
                "Diff handover margin and time-to-trigger against the known-good configuration.",
            )
        if sample.handover_success_pct < 94 and sample.call_drop_pct > 2:
            return DiagnosisRule(
                RootCauseCategory.NEIGHBOR_RELATION,
                0.84,
                "Handover failures and drops increased while radio availability remained normal.",
                "Audit bidirectional neighbor relations and target-cell reachability.",
            )
        return DiagnosisRule(
            RootCauseCategory.UNKNOWN,
            0.4,
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
