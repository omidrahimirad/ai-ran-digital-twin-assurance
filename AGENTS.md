# Repository guidance

## Architecture rules

- Keep the package in `src/ai_ran_assurance` and preserve dependency direction: domain → simulation/detection/diagnosis/twin → evaluation/API/CLI.
- Domain models are typed Pydantic objects; configuration enters through validated YAML models.
- Models and simulations must remain deterministic when given the same seed.

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

## Git workflow

- Branch from `main`, use focused conventional commits, never force-push, and do not overwrite unrelated work.
- Run the complete quality gate before publishing and prefer a squash merge after CI succeeds.

## Definition of done

The package installs; lint, formatting, typing, tests, and coverage pass; benchmark artifacts are regenerated; the API and dashboard start; Docker builds; Compose validates; docs disclose limitations; the branch is pushed; and a PR is opened or its exact blocker is recorded.
