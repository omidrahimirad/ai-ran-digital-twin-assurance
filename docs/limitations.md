# Limitations

This project is deliberately narrow. It demonstrates software architecture and assurance
logic around synthetic scenarios, not real-network performance.

## Modeling limits

- No RF propagation, fading, link budget, beamforming, scheduler, protocol stack, UE-level
  event, or packet model.
- Simple time-dependent demand and correlated KPI equations cannot reproduce operator
  traffic diversity or vendor counter semantics.
- Faults are single, deterministic, and deliberately separable. Ambiguous, concurrent,
  intermittent, slowly developing, and previously unseen faults are not benchmarked.
- The lightweight twin uses fixed response factors and does not estimate causal effects.

## ML and evaluation limits

- Isolation Forest is fitted to a clean synthetic baseline with no concept drift.
- Rule weights and prediction confidence are not calibrated probabilities.
- Perfect committed detection and diagnosis scores apply only to the eight bounded
  scenarios. They say nothing about external validity.
- The benchmark has no independent commercial, laboratory, field, or standards dataset.
- API latency uses an in-process client and does not measure concurrency or network I/O.

## Operational limits

- No live telemetry ingestion, message bus, persistence, identity, authorization, audit
  backend, high availability, or disaster recovery.
- No southbound interface or command executor is present.
- Guardrails are illustrative and not approved operator policy.
- The dashboard keeps the latest run in process and is not a multi-user experiment store.

## Standards limits

The implementation does not claim 6G compliance, O-RAN compliance, production readiness,
operator validation, or standards conformance. It does not implement NTN, ISAC, a real
O-RAN RIC, E2SM-KPM, E2SM-RC, or a real operator network.
