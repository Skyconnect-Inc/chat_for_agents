# chat_for_agents relay — FastAPI store-and-forward (ciphertext only).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    CHATAGENTS_HOME=/data

# 1. Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2. Copy the source + installer, then install the project itself.
#    README.md is required by the hatchling build (pyproject `readme` field).
COPY src ./src
COPY install.sh README.md ./
RUN uv sync --frozen --no-dev

# Persist the relay's SQLite (ciphertext + invites) across restarts.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

CMD [".venv/bin/chatagents", "relay", "--host", "0.0.0.0", "--port", "8000"]
