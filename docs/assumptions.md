# Assumptions

## Network abstraction

- Twenty cells are sufficient to demonstrate topology-aware multi-cell software behavior.
- Bidirectional degree-four relations approximate local mobility options without modeling
  geography, sectorization, bands, carriers, or UE measurements.
- Cell capacity, power, configuration, operational state, and traffic profile are known.
- One fault scenario is active per benchmark run; overlapping faults are not evaluated.

## Telemetry

- Five-minute KPI aggregates are complete, correctly timestamped, and aligned by cell.
- KPI values use the units encoded in field names.
- Ground-truth labels exist only for synthetic evaluation and are not consumed by diagnosis.
- Seeded noise is stationary within a run; distribution shift is outside the current scope.

## Detection and diagnosis

- A clean synthetic normal baseline is available for Isolation Forest training.
- Absolute thresholds are illustrative engineering policy, not operator recommendations.
- Root-cause rule confidence is ordinal and uncalibrated.
- A detected compound KPI signature has one primary root cause for scoring purposes.

## Twin and safety

- Fixed action response factors are directionally useful for software validation only.
- Prediction confidence is supplied by the response model, not learned or calibrated.
- Guardrail thresholds are demonstration constraints and must not be reused on a live RAN.
- “Approved” always means approved for shadow reporting, never approved for execution.

## Reproducibility

- Python dependencies resolve from the constrained lock file and seed 42 is used in
  benchmark mode.
- API latency varies with host load and is included only as a local smoke measurement.
- Coverage is recorded after running the complete test suite in the same checkout.
