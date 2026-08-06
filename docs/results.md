# Hardened synthetic evaluation results

> **Reported results are based on closed-set synthetic RAN scenarios and do not represent performance on a commercial mobile network.**

This is a **closed-set synthetic stress test**, not an external validation benchmark. The model is
trained with seed `17` and evaluated on seeds
`[101, 211, 307]` at severities `[0.55, 0.8]`.
Ground truth is used only by this evaluator for scoring, not by workflow selection.

## Results

| Metric | Result |
|---|---:|
| Scenario runs | 48 |
| Telemetry samples | 220800 |
| Precision | 1.0000 |
| Recall | 0.5399 |
| F1-score | 0.7012 |
| False-alarm rate | 0.0000 |
| Fault-episode detection rate | 79.17% |
| Mean delay on detected episodes | 0.0 minutes |
| RCA accuracy on diagnosed episodes | 0.526316 |
| Ambiguous RCA episodes | 18 |
| Guardrail regression cases rejected/escalated | 16/16 |
| Safe guardrail control approved | 1 |
| API health smoke | 25/25 successful |

No API latency number is reported: an in-process test client cannot establish service,
network, concurrency, or scalability performance.

## Scenario episodes

| Scenario | Runs | Detected | Correct RCA | Ambiguous RCA |
|---|---:|---:|---:|---:|
| congestion | 6 | 5 | 5 | 0 |
| interference | 6 | 6 | 3 | 3 |
| missing_neighbor | 6 | 6 | 0 | 6 |
| outage | 6 | 6 | 3 | 3 |
| transport_latency | 6 | 3 | 3 | 0 |
| coverage | 6 | 6 | 3 | 3 |
| bler | 6 | 3 | 3 | 0 |
| mobility | 6 | 3 | 0 | 3 |

Missed episodes remain false negatives. RCA accuracy is reported only where a target
episode was both detected and diagnosed; ambiguity is retained rather than forced into a
specific mobility cause. No result establishes RF accuracy, causal validity, standards
conformance, or performance on external telemetry.
