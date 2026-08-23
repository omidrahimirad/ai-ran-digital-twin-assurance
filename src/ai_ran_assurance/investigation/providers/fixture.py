"""Deterministic offline provider for contracts, CI, and pipeline demonstrations."""

from __future__ import annotations

from ai_ran_assurance.domain.enums import RootCauseCategory
from ai_ran_assurance.investigation.models import (
    Hypothesis,
    InvestigationContext,
    InvestigationOutput,
    KPIValue,
    ProviderCallResult,
    ProviderMetadata,
)


def _current_facts(context: InvestigationContext) -> tuple[str, dict[str, KPIValue]]:
    samples = [
        item
        for item in context.evidence
        if item.cell_id == context.analyzed_cell
        and item.timestamp == context.analyzed_timestamp
        and item.kind.value == "telemetry"
    ]
    if not samples:
        return context.evidence[0].evidence_id, context.anomaly.evidence
    return samples[0].evidence_id, samples[0].facts


def _value(facts: dict[str, KPIValue], field: str) -> float:
    item = facts.get(field)
    return item.value if item is not None else 0.0


def _knowledge(context: InvestigationContext, *terms: str) -> list[str]:
    for item in context.retrieved_knowledge:
        searchable = f"{item.heading} {item.text}".lower()
        if any(term.lower() in searchable for term in terms):
            return [item.chunk_id]
    return [context.retrieved_knowledge[0].chunk_id] if context.retrieved_knowledge else []


class FixtureProvider:
    """Transparent deterministic rules; fixture results are not LLM performance."""

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider="fixture",
            model="deterministic-investigation-fixture-v1",
            live_model=False,
            temperature=None,
        )

    def generate(
        self,
        context: InvestigationContext,
        *,
        system_instruction: str,
        rendered_context: str,
    ) -> ProviderCallResult:
        del system_instruction, rendered_context
        anomaly_id = context.evidence[0].evidence_id
        sample_id, facts = _current_facts(context)
        support = list(dict.fromkeys([anomaly_id, sample_id]))
        hypotheses: list[Hypothesis]

        availability = _value(facts, "availability_pct")
        sinr = _value(facts, "sinr_db")
        bler = _value(facts, "bler_pct")
        handover = _value(facts, "handover_success_pct")
        call_drop = _value(facts, "call_drop_pct")
        threshold_map = {item.metric: item.value for item in context.thresholds}
        anomaly_fields = set(context.anomaly.evidence)

        if (
            "availability_pct" in anomaly_fields
            and availability < threshold_map["availability_pct"]
        ):
            primary = RootCauseCategory.CELL_OUTAGE
            explanation = (
                "Observed availability collapse with access/service degradation is consistent "
                "with a cell-outage hypothesis; power, transport, and maintenance evidence is "
                "not supplied, so the physical cause is not confirmed."
            )
            citations = _knowledge(context, "outage", "availability")
            missing = ["Cell operational alarms", "Power and transport status"]
            checks = ["Check cell operational, power, and transport status"]
            confidence = 0.78
        elif {"prb_utilization_pct", "latency_ms"} <= anomaly_fields:
            primary = RootCauseCategory.CONGESTION
            explanation = (
                "Observed high PRB utilization with reduced throughput and elevated latency is "
                "consistent with congestion, but aggregate KPIs do not prove scheduler causality."
            )
            citations = _knowledge(context, "congestion", "capacity")
            missing = ["Traffic demand and scheduler evidence"]
            checks = ["Check persistence, offered load, and enabled-neighbor headroom"]
            confidence = 0.76
        elif "latency_ms" in anomaly_fields and sinr >= threshold_map["sinr_db"]:
            primary = RootCauseCategory.TRANSPORT
            explanation = (
                "Observed latency degradation with broadly normal radio quality is consistent "
                "with a transport-path hypothesis; no transport alarms or packet evidence was "
                "provided."
            )
            citations = _knowledge(context, "transport", "latency")
            missing = ["Transport counters, path alarms, and packet timing"]
            checks = ["Correlate transport-path counters and latency outside the radio layer"]
            confidence = 0.7
        elif {"rsrp_dbm", "sinr_db"} <= anomaly_fields:
            primary = RootCauseCategory.COVERAGE
            explanation = (
                "Observed weak RSRP with service degradation is consistent with coverage "
                "degradation; aggregate cell KPIs do not establish a propagation cause."
            )
            citations = _knowledge(context, "coverage", "RSRP")
            missing = ["Spatial or UE-level measurements", "Antenna configuration history"]
            checks = ["Compare spatial measurements and antenna configuration history"]
            confidence = 0.7
        elif "sinr_db" in anomaly_fields and "throughput_mbps" in anomaly_fields:
            primary = RootCauseCategory.INTERFERENCE
            explanation = (
                "Observed low SINR with elevated BLER and degraded service is consistent with "
                "interference, although the aggregates cannot identify an interferer."
            )
            citations = _knowledge(context, "interference", "SINR")
            missing = ["Spectrum or UE-level interference evidence"]
            checks = ["Inspect spectrum and UE-level radio measurements"]
            confidence = 0.72
        elif "bler_pct" in anomaly_fields and (
            bler > threshold_map["bler_pct"] or "throughput_mbps" in anomaly_fields
        ):
            primary = RootCauseCategory.RADIO_QUALITY
            explanation = (
                "Observed elevated BLER with throughput degradation supports a radio-quality "
                "hypothesis, but does not identify the underlying RF mechanism."
            )
            citations = _knowledge(context, "radio-quality", "BLER")
            missing = ["UE-level modulation, coding, and retransmission evidence"]
            checks = ["Inspect UE-level BLER, retransmission, and radio measurements"]
            confidence = 0.66
        elif (
            handover < threshold_map["handover_success_pct"]
            or call_drop > threshold_map["call_drop_pct"]
        ):
            primary = RootCauseCategory.UNKNOWN
            explanation = (
                "Observed mobility degradation is compatible with multiple hidden causes; "
                "aggregate KPI evidence cannot distinguish neighbor, parameter, coverage, or "
                "interference mechanisms."
            )
            citations = _knowledge(context, "mobility", "handover")
            missing = [
                "Neighbor-table and relation state",
                "Parameter-change and handover failure-cause evidence",
            ]
            checks = ["Inspect neighbor relations, parameter history, and failure-cause counters"]
            confidence = 0.42
        else:
            primary = RootCauseCategory.UNKNOWN
            explanation = (
                "The supplied aggregate evidence does not support a sufficiently specific "
                "root-cause category."
            )
            citations = _knowledge(context, "evidence", "safety")
            missing = ["Independent fault-specific telemetry or alarms"]
            checks = ["Collect independent evidence before narrowing the hypothesis"]
            confidence = 0.3

        hypotheses = [
            Hypothesis(
                category=primary,
                explanation=explanation,
                confidence=confidence,
                supporting_evidence_ids=support,
                counter_evidence_ids=[],
                knowledge_citations=citations,
                missing_evidence=missing,
                next_diagnostic_checks=checks,
            )
        ]
        if primary not in {RootCauseCategory.UNKNOWN, RootCauseCategory.INTERFERENCE}:
            hypotheses.append(
                Hypothesis(
                    category=RootCauseCategory.INTERFERENCE,
                    explanation=(
                        "Interference remains a competing hypothesis only if independent radio "
                        "measurements show degraded SINR or elevated BLER."
                    ),
                    confidence=0.22,
                    supporting_evidence_ids=[anomaly_id],
                    counter_evidence_ids=[sample_id],
                    knowledge_citations=_knowledge(context, "interference"),
                    missing_evidence=["Independent spectrum or UE-level measurements"],
                    next_diagnostic_checks=["Check SINR, BLER, and spectrum evidence"],
                )
            )
        output = InvestigationOutput(
            hypotheses=hypotheses,
            primary_hypothesis=primary,
            abstained=primary is RootCauseCategory.UNKNOWN,
            uncertainty_explanation=(
                "Aggregate synthetic KPIs are observational and omit alarms, UE traces, "
                "configuration history, packet evidence, and RF propagation state."
            ),
        )
        return ProviderCallResult(
            payload=output.model_dump(mode="json"),
            metadata=self.metadata,
        )
