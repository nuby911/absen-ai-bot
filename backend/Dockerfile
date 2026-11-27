# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

ARG INSTALL_ML=false

COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN if [ "$INSTALL_ML" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends build-essential && \
      rm -rf /var/lib/apt/lists/*; \
    fi

RUN --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_ML" = "true" ]; then \
      uv sync --frozen --no-dev --no-install-project --extra ml; \
    else \
      uv sync --frozen --no-dev --no-install-project; \
    fi

FROM python:3.11-slim AS runtime

ARG INSTALL_ML=false

RUN if [ "$INSTALL_ML" = "true" ]; then \
      apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && \
      rm -rf /var/lib/apt/lists/*; \
    fi

RUN groupadd --system --gid 1001 appgroup && \
    useradd --system --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appgroup /app/.venv /app/.venv
COPY --chown=appuser:appgroup app ./app

RUN mkdir -p /app/uploads /app/.insightface && \
    chown -R appuser:appgroup /app/uploads /app/.insightface

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    INSIGHTFACE_HOME=/app/.insightface

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
