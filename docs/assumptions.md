# Assumptions

## Synthetic network

- Twenty cells and degree-four directed neighbor choices are sufficient for software
  behavior tests, not network dimensioning.
- Geography, sectors, bands, carriers, UEs, beams, propagation, scheduler state, and
  protocol events are absent.
- Capacity, transmit power, local configuration, neighbor state, and five-minute KPI
  aggregates are assumed known and internally consistent.
- Exactly one configured fault occurs per evaluation episode.

## Telemetry generation

- KPI names encode the units used by the equations; they are not mapped to vendor PM
  counters or 3GPP measurement definitions.
- Seeded cell bias and autoregressive state are stable within a run. Morning/evening
  demand peaks are illustrative, not fitted to traffic traces.
- Samples are complete, timezone-aware, and aligned by timestamp and cell. Missing,
  duplicated, delayed, and out-of-order ingestion are not generated.
- Synthetic ground truth exists for injection and evaluation. Workflow selection and RCA
  do not consume it.

## Detection and diagnosis

- A prequalified all-normal 24-hour synthetic baseline is available for model fitting.
  Mixed labeled data is rejected instead of cleaned silently.
- Training and evaluation seeds differ, but both come from the same generator family.
- Thresholds are illustrative policy values, not operator recommendations.
- RCA confidence is an ordinal rule weight, not a calibrated probability.
- Similar mobility signatures are intentionally reported as unknown until topology or
  configuration evidence is available.

## Response surrogate and safety

- What-if equations are used only to verify software contracts and guardrails.
- Prediction confidence is manually assigned by action class and uncalibrated.
- Guardrail thresholds do not constitute an operator safety case.
- An approved result is only eligible for shadow display and cannot authorize execution.

## Evaluation and reproduction

- The committed protocol uses training seed `17`, evaluation seeds `101`, `211`, and
  `307`, and severities `0.55` and `0.8`.
- Ground truth is used by the evaluator to identify positive samples and episode evidence.
- Detection delay is reported only on detected episodes; missed episodes remain false
  negatives and are separately visible in episode detection rate.
- Coverage is captured by the full test suite before artifact generation.
- API checks establish functional health only. No latency, load, concurrency, or
  scalability claim is made.
