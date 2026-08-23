# AI investigation V2: product and engineering design

## User and problem

The intended user is an engineer investigating synthetic RAN degradation. The problem is
not “add an LLM.” Deterministic KPI rules are valuable because they are reproducible,
inspectable, and safe to place before a fixed action policy, but they have limited ability
to synthesize a wider evidence window, articulate competing explanations, retrieve
troubleshooting knowledge, and state what evidence is missing.

V2 therefore adds an optional **advisory investigation layer**. It never replaces the
deterministic root-cause engine and never enters the action authority path.

## Why AI may help

The structured provider task is limited to:

- synthesizing bounded observable KPI, anomaly, topology, threshold, and history context;
- generating a primary and competing diagnostic hypothesis;
- citing the evidence and retrieved engineering knowledge used;
- explaining uncertainty and missing evidence; and
- proposing further diagnostic checks that a qualified engineer can review.

These are language-and-evidence synthesis tasks. They remain hypotheses, not causal proof.

## Why AI is not used for control

AI output is not used for trusted KPI calculations, topology/configuration mutation,
candidate-action generation, twin response calculation, guardrail approval, or network
actuation. The existing path remains authoritative:

```text
RootCauseEngine → ActionRecommender → TwinSimulator → GuardrailValidator → ShadowDecision
```

The AI layer cannot return a `CorrectiveAction`, `TwinPrediction`, `GuardrailResult`, or
`ShadowDecision`. Its report contract states `can_modify_shadow_decision: false`. There is
no southbound client or autonomous tool loop.

## Context and trust boundary

`InvestigationContextBuilder` does not accept `FaultScenario` or `ScenarioRun`. Its inputs
are explicitly limited to topology, telemetry, one detected anomaly, engineering thresholds,
and—only in review mode—a deterministic RCA candidate. It enumerates observable KPI fields
instead of serializing `KPISample`, because the latter contains evaluation truth.

At timestamp `T`, telemetry is filtered to `timestamp <= T`. The current-cell lookback,
same-timestamp enabled-neighbor snapshot, evidence count, and retrieval count are bounded and
deterministically ordered. Context export is explicit, never automatic.

Retrieved Markdown is wrapped as `UNTRUSTED_DATA_NOT_INSTRUCTIONS`. The provider receives no
tools and cannot execute document instructions. A local TF-IDF retriever supplies stable chunk
IDs and source paths.

## Structured provider and verifier

Providers return only `InvestigationOutput`, validated by strict Pydantic models. Hypothesis
count, text length, references, citations, diagnostic checks, and confidence are bounded. The
offline fixture exercises contracts and CI. The optional OpenAI Responses adapter uses a strict
JSON schema, bounded timeout/retries/output, disabled storage, no tools, and explicit live-call
opt-in. Secrets come only from environment variables and are never logged.

Valid JSON is still untrusted. `EvidenceVerifier` checks evidence and citation membership,
unsupported observation claims, high-confidence support, explicit abstention, context identity,
and unsafe actuation language. Results are `verified`, `partially_verified`, `rejected`, or
`abstained`.

## Success criteria

- zero scenario/truth fields in provider context;
- zero future samples at an analyzed timestamp;
- resolvable evidence and knowledge references;
- explicit abstention on intentionally ambiguous aggregate mobility evidence;
- provider/schema/safety failure represented without core failure;
- identical anomalies, deterministic diagnoses, recommendations, twin/guardrail results, and
  shadow decisions with and without advisory investigation; and
- reproducible error analysis that distinguishes retrieval, grounding, confidence, schema,
  diagnostic, ambiguity, and safety failures.

## Failure modes and mitigations

| Failure | Deterministic response |
|---|---|
| Hallucinated evidence/citation | Reject the advisory result. |
| Overconfidence with weak support | Mark partially verified. |
| Ambiguous evidence | Permit/expect `unknown` and abstention. |
| Prompt-like retrieved text | Treat it as untrusted data; no tool execution exists. |
| Empty retrieval | Reason from supplied evidence or abstain. |
| Stale/future context | Context construction excludes future data; core guardrails retain independent freshness checks. |
| Provider timeout or invalid JSON | Return a rejected advisory report; core assurance remains available. |
| Unsafe actuation language | Reject the advisory result; no action interface is exposed to the provider. |

## Product boundary

This remains an offline, synthetic, simulation-based engineering prototype. It has no
operator dataset, live telemetry, RF propagation model, O-RAN interface, standards-conformance
claim, provider qualification, authentication layer, or network actuation.
