FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
COPY dashboard ./dashboard
RUN pip install .

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000 8501
CMD ["python", "-m", "ai_ran_assurance.cli", "serve-api"]
