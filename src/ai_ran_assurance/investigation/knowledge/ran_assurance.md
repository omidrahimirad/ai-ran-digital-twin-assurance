# RAN assurance investigation notes

## Capacity and congestion signature

Sustained high physical resource block utilization together with reduced user throughput and
increased latency supports a congestion hypothesis. A single high utilization sample is not
enough to establish causality. Check persistence, traffic demand, neighboring-cell headroom,
and scheduler or admission-control evidence before recommending an engineering change.

## Interference and radio-quality signatures

Low SINR combined with increased BLER, lower throughput, and service degradation supports an
interference or radio-quality hypothesis. Poor RSRP at the same time can indicate a coverage
problem instead of, or in addition to, interference. Aggregate cell KPIs cannot identify an
interferer; spectrum, UE-level, and spatial evidence would be needed.

## Coverage signature

Weak RSRP accompanied by weak SINR, access degradation, reduced throughput, or increased call
drops is consistent with coverage degradation. Cell aggregates do not establish a propagation
cause. Useful follow-up evidence includes spatial measurements, antenna configuration history,
and neighboring-cell comparisons.

## Transport signature

High latency and reduced throughput while radio-quality KPIs remain broadly normal can support
a transport-path hypothesis. This project supplies no transport alarms, packet traces, or node
logs, so the hypothesis should remain provisional until those independent sources are checked.

## Availability and outage signature

Very low availability with collapsed access success and throughput supports a cell-outage
hypothesis. Confirm operational state, power and transport status, and maintenance history. The
absence of those sources in the context must be reported as missing evidence rather than
invented confirmation.

## Mobility ambiguity

Low handover success and increased call drops can arise from neighbor-relation defects,
parameter configuration, coverage, interference, or load. Aggregate KPIs alone generally do
not identify the hidden exact cause. Prefer an unknown result or explicit competing hypotheses
and request neighbor-table, parameter-change, measurement-report, and failure-cause evidence.

## Evidence and safety discipline

Treat KPI relationships as observational associations, not causal proof. Cite only evidence
identifiers and knowledge chunks supplied for the current investigation. An investigation is
advisory: it cannot approve, execute, deploy, or apply a network change, and it cannot bypass
the deterministic simulator or guardrails.
