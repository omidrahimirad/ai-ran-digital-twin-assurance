# Repository guidance

## Project purpose and trust boundary

- This is a synthetic, simulation-based RAN assurance prototype with an optional advisory AI
  investigation layer.
- The authoritative path is `RootCauseEngine → ActionRecommender → TwinSimulator →
  GuardrailValidator → ShadowDecision`.
- AI investigation may explain observable evidence, retrieve project knowledge, identify
  competing hypotheses, and abstain. It must never create or approve an action, alter core
  output, bypass guardrails, or execute a network change.
- Evaluation truth (`FaultScenario`, target cells/windows, severity, labels, and
  `KPISample.ground_truth`) must never enter investigation context. Context at timestamp `T`
  must never contain telemetry after `T`.

## Architecture rules

- Keep the package in `src/ai_ran_assurance` and preserve dependency direction: domain → simulation/detection/diagnosis/twin → evaluation/API/CLI.
- Domain models are typed Pydantic objects; configuration enters through validated YAML models.
- Models and simulations must remain deterministic when given the same seed.
- Keep investigation dependencies one-way: domain/config → investigation support →
  evaluation/API/CLI/dashboard. Do not import evaluation truth into `investigation/`.

## Coding standards

- Support Python 3.11+, Ruff formatting/linting, and strict MyPy.
- Prefer small pure functions, explicit interfaces, structured logging, and vendor-neutral naming.
- Never commit secrets, large generated telemetry, or runtime caches.

## Telecom terminology and truthful claims

- State that data is synthetic and the simulator is an engineering abstraction, not RF-accurate.
- Say “simulation-based”, “6G-aligned”, “IMT-2030-inspired”, “AI-assisted”, “lightweight”, and “shadow mode”.
- Never claim 6G/O-RAN compliance, standards conformance, production readiness, operator validation, live integration, or real-RAN autonomous execution.

## Testing requirements

- Cover unit, integration, API, invalid configuration, deterministic reproduction, safety rejection, stale telemetry, and complete closed-loop behavior.
- Generate reported metrics only by executing the benchmark. Maintain at least 85% core-package coverage.
- Treat fixture-provider metrics as offline contract checks, never live-model performance. Live
  calls require explicit opt-in and must never run in CI.

## Important files

- `src/ai_ran_assurance/workflow.py`: authoritative deterministic workflow.
- `src/ai_ran_assurance/investigation/`: observable context, retrieval, providers, prompts,
  verifier, and advisory orchestration.
- `src/ai_ran_assurance/evaluation/benchmark.py`: original deterministic benchmark.
- `src/ai_ran_assurance/evaluation/ai_benchmark.py`: separate investigation evaluator; truth is
  scorer-only.
- `docs/architecture.md`, `docs/ai_engineering_v2.md`, and `docs/ai_evaluation.md`: design and
  claim boundaries.

## Git workflow

- Branch from `main`, use focused conventional commits, never force-push, and do not overwrite unrelated work.
- Run the complete quality gate before publishing and prefer a squash merge after CI succeeds.

## Definition of done

The package installs; lint, formatting, typing, tests, and coverage pass; benchmark artifacts are regenerated; the API and dashboard start; Docker builds; Compose validates; docs disclose limitations; the branch is pushed; and a PR is opened or its exact blocker is recorded.

Before completion also run the offline fixture evaluation and confirm no artifact diff:

```bash
uv run --frozen ai-ran-assurance evaluate-ai --provider fixture --profile smoke
git diff --exit-code -- reports/ai_evaluation
```
