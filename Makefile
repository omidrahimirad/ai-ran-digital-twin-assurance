.PHONY: install lint format type test coverage benchmark demo api dashboard quality

install:
	uv sync --extra dev

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

quality: lint format type coverage benchmark
