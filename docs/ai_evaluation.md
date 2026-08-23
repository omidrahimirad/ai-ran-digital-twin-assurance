# Advisory investigation evaluation

## Evaluation boundary

AI-investigation evaluation is separate from the existing deterministic benchmark. The
investigator receives only an `InvestigationContext`; the evaluator alone retains scenario
identifier, injected category, target/interval metadata, and severity for scoring. Operational
anomaly selection ranks detector output without using target cells or fault windows.

The context is recursively checked for forbidden answer-key fields before each record is
scored. A separate hard regression compares core outputs from identical configuration and
seeds before and after advisory investigation.

## Profiles and providers

- `smoke`: eight scenarios, one seed, one severity; committed as a small contract artifact.
- `full`: eight scenarios, three seeds, two severities; run locally when broader fixture or
  explicitly opted-in live evaluation is needed.
- `fixture`: deterministic rules used to test pipeline mechanics, schemas, verification,
  abstention, and reproducibility. Fixture scores are **not LLM performance**.
- `openai`: optional schema-constrained live adapter. It requires explicit live-provider and
  live-evaluation flags plus credentials/model configuration. No live result is committed.

CI and default development commands never call a paid model.

## Metrics

The evaluator reports:

- strict top-1 agreement across all cases;
- top-1 agreement on non-ambiguous cases;
- unknown/abstention rate;
- ambiguity-respect and ambiguous-overclaim rates;
- evidence-reference and knowledge-citation validity;
- unsupported-reference and verifier-rejection rates;
- unsafe-actuation suggestion violations;
- provider/schema failures; and
- core-decision isolation pass rate.

For live providers, each record also preserves genuine latency, input/output token usage, and
temperature when the provider supplies them. Provider transport failures and Pydantic schema
failures have distinct machine-readable failure kinds and rates; unavailable values remain null.

Missing-neighbor and mobility-configuration injections are marked evaluator-side as
intentionally ambiguous because their aggregate KPI evidence does not identify the hidden exact
cause. Abstention is appropriate; guessing the answer key is not.

## Error taxonomy

Each record is assigned one of:

- `provider_or_schema_failure`;
- `invalid_evidence_reference`;
- `invalid_knowledge_citation`;
- `unsupported_observation`;
- `unsafe_action_suggestion`;
- `ambiguous_case_overclaimed`;
- `unnecessary_abstention`;
- `correct_evidence_wrong_rca`;
- `insufficient_support_overconfident`;
- `retrieval_empty`; or
- `none`.

The generated CSV retains evaluator-only truth metadata beside output/verification summaries,
not inside provider context.

## Reproduction

```bash
uv run --frozen ai-ran-assurance evaluate-ai \
  --provider fixture \
  --profile smoke \
  --output-dir reports/ai_evaluation
git diff --exit-code -- reports/ai_evaluation
```

The baseline artifact contains eight deterministic fixture cases. It is labeled
`deterministic_fixture_contract`; it does not establish generalization, model quality, field
performance, or AI accuracy.

## Deterministic-baseline comparison

The existing deterministic RCA remains the authoritative comparison in
[`results.md`](results.md). The fixture provider is another deterministic contract mechanism,
not an AI system, so its agreement rate is not used to claim improvement over that baseline.
No verified AI-versus-deterministic accuracy comparison is published until a named live model is
run under the documented protocol.

## Explicit live evaluation

Live calls require all of the following and are never made by CI:

```bash
AI_RAN_ENABLE_LIVE_PROVIDER=1 \
AI_RAN_RUN_LIVE_EVAL=1 \
OPENAI_API_KEY=... \
AI_RAN_OPENAI_MODEL=... \
uv run --frozen ai-ran-assurance evaluate-ai --provider openai --profile smoke
```

A live run should record provider/model, genuine token usage and latency when returned, prompt
version, retrieval/context configuration, seeds, severity, verification outcome, and errors.
Cost is omitted unless it can be calculated from an authoritative price snapshot. No live-model
benchmark is reported in this repository.

## Limitations

Synthetic closed-set evidence is substantially simpler than field troubleshooting. The corpus
is small and project-created. TF-IDF relevance is lexical, not semantic. The verifier checks
reference integrity and bounded safety policies; it does not prove every natural-language claim
true. Live-model variance, provider drift, privacy review, domain calibration, and adversarial
evaluation remain future work.
