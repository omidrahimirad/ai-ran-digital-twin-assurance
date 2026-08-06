# Methodology

## Synthetic network and KPI model

The topology is a deterministic 20-node ring with local chord neighbors. Five-minute
traffic follows a daily sinusoid with cell-specific phase variation and seeded noise.
KPIs are related rather than sampled independently:

- SINR is a function of RSRP, load-related interference, and small noise.
- BLER grows when SINR falls.
- Throughput combines configured capacity, a SINR-derived spectral factor, congestion
  pressure, and BLER loss.
- RRC success reacts to availability and overload.
- Handover success reacts to interference before fault-specific effects.
- Call drops react to BLER and handover failure.
- Latency reacts to load and BLER before transport or congestion fault effects.

These equations are engineering abstractions designed for software assurance tests. They
do not implement link budgets, propagation, scheduler behavior, protocol timing, or an RF
channel model.

## Fault injection

Each YAML scenario declares its target, start step, duration, severity, affected KPIs,
and ground-truth cause. Fault effects are deterministic multipliers or offsets applied
after baseline relationships and before KPI bounds. The same seed therefore reproduces
the same normal and faulty time series.

## Detection

The interpretable detector combines configured absolute thresholds with a past-only
rolling window. Rolling findings require at least two KPI Z-scores beyond the configured
limit. The Isolation Forest uses standardized KPI vectors, a fixed seed, one execution
thread, and only samples labeled `normal` during fitting. No deep learning is used.

The workflow admits all hard-threshold findings. Statistical-only findings require an
Isolation Forest finding for the identical cell/timestamp. Configuration and detector
logic were fixed before generating the committed results; the benchmark does not search
hyperparameters against its own output.

## Explainable diagnosis

Ordered vendor-neutral rules recognize compound signatures such as outage, congestion,
interference, coverage loss, transport delay, BLER degradation, neighbor failure, and
mobility misconfiguration. Output includes a category, confidence, evidence, plain-language
explanation, and next diagnostic check. Confidence values are rule weights, not calibrated
probabilities.

## Twin and guardrails

The twin deep-copies network and current state. It supports restoring a neighbor,
steering traffic, rolling back a parameter, activating capacity, and requesting human
review. Fixed response factors create before/after KPI predictions.

Guardrails check predicted handover/RRC success, availability loss, latency, parameter
delta, cooldown, telemetry age, and prediction confidence. A human-review action always
escalates. No result triggers real actuation.

## Evaluation protocol

The benchmark executes all eight scenarios with seed 42 and evaluates every cell/time
sample. A sample is positive only inside its configured target fault interval.

- Precision, recall, F1, false-alarm rate: binary sample-level detection.
- Detection delay: first target-cell finding minus scenario start.
- Root-cause accuracy: diagnosed category versus configured cause per scenario.
- Unsafe rejection: eight independently constructed safety violations.
- API latency: 25 sequential in-process `GET /health` calls; not a load test.
- Coverage: the measured `pytest-cov` JSON total when generated before the benchmark.

Exact machine-readable counts and results are in `artifacts/sample_results.json`.
