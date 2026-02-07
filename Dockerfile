# ---- Builder stage ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./

# Install the project itself
RUN uv sync --frozen --no-dev

# ---- Runtime stage ----
FROM python:3.13-slim-bookworm

WORKDIR /app

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source and alembic
COPY --from=builder /app/app/ app/
COPY --from=builder /app/alembic/ alembic/
COPY --from=builder /app/alembic.ini ./

# Put venv on PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
