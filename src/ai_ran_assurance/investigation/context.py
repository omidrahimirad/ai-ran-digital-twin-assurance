"""Leakage-safe, deterministic construction of observable investigation context."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from ai_ran_assurance.config import InvestigationSettings, ThresholdSettings
from ai_ran_assurance.domain.models import (
    KPI_FIELDS,
    Anomaly,
    KPISample,
    NetworkTopology,
    RootCauseDiagnosis,
)
from ai_ran_assurance.investigation.models import (
    CandidateAssessment,
    ContextMetadata,
    EvidenceItem,
    EvidenceKind,
    InvestigationContext,
    InvestigationMode,
    KPIValue,
    ObservableAnomaly,
    ThresholdEvidence,
    TopologyRelation,
)
from ai_ran_assurance.investigation.retrieval import LexicalRetriever

KPI_UNITS = {
    "rsrp_dbm": "dBm",
    "sinr_db": "dB",
    "bler_pct": "%",
    "prb_utilization_pct": "%",
    "throughput_mbps": "Mbit/s",
    "rrc_success_pct": "%",
    "handover_success_pct": "%",
    "call_drop_pct": "%",
    "latency_ms": "ms",
    "availability_pct": "%",
}

THRESHOLD_FIELDS: dict[str, tuple[str, Literal["minimum", "maximum"]]] = {
    "rsrp_min_dbm": ("rsrp_dbm", "minimum"),
    "sinr_min_db": ("sinr_db", "minimum"),
    "bler_max_pct": ("bler_pct", "maximum"),
    "prb_utilization_max_pct": ("prb_utilization_pct", "maximum"),
    "throughput_min_mbps": ("throughput_mbps", "minimum"),
    "rrc_success_min_pct": ("rrc_success_pct", "minimum"),
    "handover_success_min_pct": ("handover_success_pct", "minimum"),
    "call_drop_max_pct": ("call_drop_pct", "maximum"),
    "latency_max_ms": ("latency_ms", "maximum"),
    "availability_min_pct": ("availability_pct", "minimum"),
}


def _kpi_values(values: dict[str, float]) -> dict[str, KPIValue]:
    return {
        field: KPIValue(value=float(value), unit=KPI_UNITS[field])
        for field, value in sorted(values.items())
        if field in KPI_FIELDS
    }


def _observable_values(sample: KPISample) -> dict[str, KPIValue]:
    # Intentionally enumerate only observable KPIs. KPISample.ground_truth is never dumped.
    return _kpi_values({field: float(getattr(sample, field)) for field in sorted(KPI_FIELDS)})


def _candidate(diagnosis: RootCauseDiagnosis | None) -> CandidateAssessment | None:
    if diagnosis is None:
        return None
    return CandidateAssessment(
        category=diagnosis.probable_root_cause,
        confidence=diagnosis.confidence,
        explanation=diagnosis.explanation,
        evidence_kpis=_kpi_values(diagnosis.evidence_kpis),
        next_diagnostic_check=diagnosis.next_diagnostic_check,
    )


def _relations(topology: NetworkTopology, cell_id: str) -> list[TopologyRelation]:
    return [
        TopologyRelation(
            source_cell=item.source_cell,
            target_cell=item.target_cell,
            enabled=item.enabled,
        )
        for item in sorted(
            (
                relation
                for relation in topology.neighbor_relations
                if cell_id in {relation.source_cell, relation.target_cell}
            ),
            key=lambda relation: (relation.source_cell, relation.target_cell),
        )
    ]


def _thresholds(settings: ThresholdSettings) -> list[ThresholdEvidence]:
    return [
        ThresholdEvidence(
            metric=metric,
            operator=operator,
            value=float(getattr(settings, field)),
            unit=KPI_UNITS[metric],
        )
        for field, (metric, operator) in THRESHOLD_FIELDS.items()
    ]


def _query(anomaly: Anomaly) -> str:
    evidence = " ".join(field.replace("_", " ") for field in sorted(anomaly.evidence))
    return f"RAN assurance {anomaly.anomaly_type.value} {evidence} diagnosis troubleshooting"


def select_anomaly(anomalies: Iterable[Anomaly], cell_id: str | None = None) -> Anomaly:
    """Select observable evidence only; never use scenario target or active-window truth."""
    candidates = [item for item in anomalies if cell_id is None or item.cell_id == cell_id]
    if not candidates:
        suffix = f" for {cell_id}" if cell_id else ""
        raise ValueError(f"no detected anomaly is available{suffix}")
    return sorted(
        candidates,
        key=lambda item: (-item.score, item.timestamp, item.cell_id, item.detector),
    )[0]


class InvestigationContextBuilder:
    def __init__(
        self,
        settings: InvestigationSettings,
        thresholds: ThresholdSettings,
        retriever: LexicalRetriever,
    ) -> None:
        self.settings = settings
        self.threshold_settings = thresholds
        self.retriever = retriever

    def build(
        self,
        *,
        topology: NetworkTopology,
        telemetry: list[KPISample],
        anomaly: Anomaly,
        mode: InvestigationMode = InvestigationMode.INDEPENDENT,
        deterministic_candidate: RootCauseDiagnosis | None = None,
    ) -> InvestigationContext:
        if mode is InvestigationMode.INDEPENDENT and deterministic_candidate is not None:
            raise ValueError("independent mode cannot receive deterministic RCA")
        if mode is InvestigationMode.REVIEW and deterministic_candidate is None:
            raise ValueError("review mode requires deterministic RCA")
        known_cells = {cell.cell_id for cell in topology.cells}
        if anomaly.cell_id not in known_cells:
            raise ValueError("anomaly references a cell outside the supplied topology")

        eligible = [sample for sample in telemetry if sample.timestamp <= anomaly.timestamp]
        analyzed_cell_samples = sorted(
            (sample for sample in eligible if sample.cell_id == anomaly.cell_id),
            key=lambda sample: (sample.timestamp, sample.step),
        )
        current_samples = [
            sample for sample in analyzed_cell_samples if sample.timestamp == anomaly.timestamp
        ]
        if not current_samples:
            raise ValueError("anomaly timestamp has no matching observable telemetry")
        current_sample = current_samples[-1]
        recent_history = [
            sample
            for sample in reversed(analyzed_cell_samples)
            if sample.timestamp < anomaly.timestamp
        ][: self.settings.context_lookback_samples - 1]

        relation_models = _relations(topology, anomaly.cell_id)
        neighbor_ids = sorted(
            {
                relation.target_cell
                if relation.source_cell == anomaly.cell_id
                else relation.source_cell
                for relation in relation_models
                if relation.enabled
            }
        )
        neighbor_snapshot = sorted(
            (
                sample
                for sample in eligible
                if sample.timestamp == anomaly.timestamp and sample.cell_id in neighbor_ids
            ),
            key=lambda sample: (sample.cell_id, sample.step),
        )

        evidence: list[EvidenceItem] = [
            EvidenceItem(
                evidence_id=(
                    f"ev-anomaly-{anomaly.cell_id.lower()}-{int(anomaly.timestamp.timestamp())}"
                ),
                timestamp=anomaly.timestamp,
                cell_id=anomaly.cell_id,
                kind=EvidenceKind.ANOMALY,
                source=anomaly.detector,
                facts=_kpi_values(anomaly.evidence),
                description=(
                    f"{anomaly.anomaly_type.value} anomaly with detector score "
                    f"{anomaly.score:.3f}; score is not a calibrated probability."
                ),
            )
        ]
        prioritized_samples = [current_sample, *recent_history, *neighbor_snapshot]
        remaining_budget = self.settings.max_evidence_items - len(evidence)
        for sample in prioritized_samples[:remaining_budget]:
            evidence.append(
                EvidenceItem(
                    evidence_id=f"ev-kpi-{sample.cell_id.lower()}-step-{sample.step}",
                    timestamp=sample.timestamp,
                    cell_id=sample.cell_id,
                    kind=EvidenceKind.TELEMETRY,
                    source="synthetic_kpi_aggregate",
                    facts=_observable_values(sample),
                    description=(
                        "Observable five-minute synthetic KPI aggregate for the analyzed cell."
                        if sample.cell_id == anomaly.cell_id
                        else "Same-timestamp synthetic KPI aggregate for an enabled neighbor."
                    ),
                )
            )
        knowledge = self.retriever.retrieve(_query(anomaly), top_k=self.settings.retrieval_top_k)
        observable_anomaly = ObservableAnomaly(
            cell_id=anomaly.cell_id,
            timestamp=anomaly.timestamp,
            anomaly_type=anomaly.anomaly_type,
            score=anomaly.score,
            detector=anomaly.detector,
            evidence=_kpi_values(anomaly.evidence),
        )
        return InvestigationContext(
            analyzed_cell=anomaly.cell_id,
            analyzed_timestamp=anomaly.timestamp,
            mode=mode,
            anomaly=observable_anomaly,
            evidence=evidence,
            topology_relations=relation_models,
            thresholds=_thresholds(self.threshold_settings),
            retrieved_knowledge=knowledge,
            candidate_assessment=_candidate(deterministic_candidate),
            metadata=ContextMetadata(
                lookback_samples=self.settings.context_lookback_samples,
                evidence_limit=self.settings.max_evidence_items,
                included_telemetry_samples=sum(
                    item.kind is EvidenceKind.TELEMETRY for item in evidence
                ),
                retrieval_limit=self.settings.retrieval_top_k,
            ),
        )
