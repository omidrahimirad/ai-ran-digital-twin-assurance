# Methodology

## Synthetic topology and time series

The topology is a deterministic 20-node ring-plus-chords graph with four directed,
enabled neighbor choices per cell. Each five-minute step uses:

- fixed seeded cell shadowing and traffic bias;
- autoregressive load, signal, and interference state;
- illustrative morning and evening demand peaks;
- offered demand bounded below configured capacity;
- transmit-power and cell-shadowing effects on RSRP;
- load-related interference in SINR;
- a logistic SINR-to-BLER relationship;
- achievable radio throughput constrained by capacity and radio efficiency;
- PRB demand derived from offered versus achievable throughput;
- nonlinear queue pressure in latency; and
- BLER/mobility relationships in access, handover, and drop KPIs.

The generator always uses a local NumPy random generator. Equal configuration, start
time, step count, scenario, and seed produce equal telemetry. A timezone-naive start is
rejected. These equations are transparent test fixtures, not RF, scheduler, or protocol
models.

## Fault injection

Each validated scenario declares a unique name, mapped fault type and truth category,
known target cells, active interval, severity, and the complete set of directly modified
KPIs. Injection applies deterministic bounded offsets/multipliers after baseline KPI
relationships. Throughput remains bounded by configured cell capacity.

The injector truth is not automatically a defensible RCA. In particular, missing-neighbor
and mobility-parameter injection produce similar aggregate KPIs. The workflow reports
that ambiguity rather than recovering the label.

## Training and anomaly detection

Isolation Forest training uses a separately generated 24-hour baseline and a fixed
single-thread seed. Fitting rejects a mixed baseline if any sample is not marked normal;
it does not use labels to filter convenient rows. Standardization is fitted only on the
training baseline.

The rule detector processes timestamp-sorted samples and calculates rolling statistics
only from prior samples for that cell. Hard threshold breaches are admitted directly.
Statistical-only findings require Isolation Forest agreement on the identical cell and
timestamp. The configuration was not optimized against the reported evaluation seeds.

## Diagnosis and action policy

RCA applies ordered compound KPI rules for strong outage/degradation, congestion,
interference, coverage, transport, and BLER signatures. A mobility failure/drop signature
without topology or configuration evidence returns `unknown` at low confidence. Output
contains evidence, an explanation, and a next diagnostic check.

Only diagnosed congestion maps to a 15% capacity candidate. Interference, coverage,
transport, outage, radio-quality, mobility, unknown, and normal categories map to explicit
human review. This avoids pretending that aggregate KPIs prove a safe configuration
change.

## Copied state and response equations

The state surrogate requires non-empty telemetry with one known cell per record and one
common timestamp. The main workflow supplies the full twenty-cell timestamp state.

- Capacity activation reduces modeled PRB by a capacity ratio, adjusts queue-related
  latency, and permits at most a small throughput increase under high load.
- Traffic steering requires an enabled, available neighbor with PRB headroom and records
  the source and impacted target effects.
- Neighbor restoration can only enable a specifically named relation that exists and is
  disabled.
- Parameter rollback verifies the claimed current value against copied configuration and
  uses a small local response.
- Human review predicts no KPI change.

Every response lists assumptions and a deliberately low, uncalibrated confidence. The
model description states that this is not causal, RF-calibrated, or a live prediction.

## Guardrails and API trust boundary

Guardrails fail closed on mismatched action/prediction identity, primary or impacted-cell
KPI limits, absolute/relative availability, excessive action size, cooldown, future
history, stale/future telemetry, proposal chronology, diagnosis confidence, response
confidence, and human-review requests.

Synthetic replay evaluates an action against the latest timestamp in that replay. The
API uses server time and only accepts a timestamp/cell present in stored telemetry. It
recomputes the response; prediction bodies and evaluation timestamps supplied by a client
are forbidden by the request schema.

## Evaluation protocol

The committed benchmark uses one engine trained with seed `17`, then evaluates all eight
configured fault types at severities `0.55` and `0.8` with seeds `101`, `211`, and `307`.
That produces 48 episodes and 220,800 cell/time samples.

- Sample precision, recall, F1, and false-alarm rate compare findings with injected
  target/active-window truth.
- Episode detection requires at least one target-cell finding during the fault interval.
- Detection delay is calculated only for detected episodes and is labeled accordingly.
- RCA scoring applies the same RCA engine to the first detected target evidence; truth is
  used only to select and score that evidence.
- Ambiguous diagnoses remain incorrect for exact injected-cause accuracy and are counted
  separately.
- Guardrail regression contains one explicit safe control plus sixteen isolated unsafe
  or escalation cases.
- API health is 25 successful in-process requests; timing is intentionally omitted.
- Coverage is checked separately by CI because small platform-specific branch differences
  do not belong in the deterministic benchmark artifact.

The artifact is a closed-set stress test, not an external benchmark.
