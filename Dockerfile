FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install agentgateway binary
COPY --from=cr.agentgateway.dev/agentgateway:0.11.1 /usr/local/bin/agentgateway /usr/local/bin/agentgateway

# Python dependencies
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Gateway config
COPY gateway/config.yaml /etc/reelm/gateway.yaml

ENV HOST=0.0.0.0 PORT=8000 UV_NO_SYNC=true
EXPOSE 8000 3000
CMD ["sh", "-c", "uv run uvicorn mcps.server:jackett --host 0.0.0.0 --port $PORT"]
