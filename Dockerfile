# ---- Builder stage ----
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

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
FROM python:3.14-slim-bookworm

WORKDIR /app

ARG TECTONIC_VERSION=0.15.0

# Install Tectonic (LaTeX engine) for invoice rendering in Linux deploys
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl tar; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) target="x86_64-unknown-linux-gnu" ;; \
      arm64) target="aarch64-unknown-linux-musl" ;; \
      *) echo "Unsupported architecture for tectonic: $arch"; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/tectonic.tar.gz \
      "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic@${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${target}.tar.gz"; \
    binary_path="$(tar -tzf /tmp/tectonic.tar.gz | head -n1)"; \
    tar -xzf /tmp/tectonic.tar.gz -C /tmp; \
    install -m 0755 "/tmp/${binary_path}" /usr/local/bin/tectonic; \
    rm -f /tmp/tectonic.tar.gz "/tmp/${binary_path}"; \
    rm -rf /var/lib/apt/lists/*

# Copy the virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source and alembic
COPY --from=builder /app/app/ app/
COPY --from=builder /app/alembic/ alembic/
COPY --from=builder /app/alembic.ini ./
COPY templates/ templates/
COPY data/bot_only_suspend_emails.txt data/bot_only_suspend_emails.txt

# Put venv on PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV INVOICE_LATEX_ENGINE=tectonic

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
