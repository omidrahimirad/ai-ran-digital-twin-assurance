.PHONY: install lint format type test coverage benchmark demo api dashboard security quality

install:
	uv sync --frozen --extra dev

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

type:
	uv run mypy src

test:
	uv run pytest

coverage:
	uv run pytest --cov=ai_ran_assurance --cov-report=term-missing

benchmark:
	uv run python scripts/run_benchmark.py

demo:
	uv run python -m ai_ran_assurance.cli demo --scenario congestion

api:
	uv run python -m ai_ran_assurance.cli serve-api

dashboard:
	uv run streamlit run dashboard/app.py

security:
	uv export --quiet --frozen --no-dev --no-emit-project --format requirements-txt --output-file /tmp/ai-ran-runtime-requirements.txt
	uvx --from pip-audit==2.9.0 pip-audit --requirement /tmp/ai-ran-runtime-requirements.txt --disable-pip
	uvx --from bandit==1.8.6 bandit -q -r src dashboard scripts

quality: lint format type coverage security benchmark
