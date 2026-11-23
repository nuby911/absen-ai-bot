# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project

FROM python:3.11-slim AS runtime

RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup app ./app

RUN mkdir -p /app/uploads && chown -R appuser:appgroup /app/uploads

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
