# syntax=docker/dockerfile:1.7
#
# hvac-mcp container image.
# Builds a slim Python 3.11 image running the streamable-HTTP MCP server.
# Railway / Fly / any PaaS: set PORT env var; image binds 0.0.0.0 by default.
#
# Build:  docker build -t hvac-mcp .
# Run:    docker run -p 8000:8000 -e HVAC_MCP_LICENSE_KEY=... hvac-mcp

FROM python:3.11-slim AS base

# System deps: just the bare minimum for uv + Python wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for better layer caching.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Install the package and its dependencies into a system Python env.
# --no-dev skips test/lint deps; keeps the image lean.
RUN uv sync --frozen --no-dev 2>/dev/null \
    || uv pip install --system -e .

# Non-root user for runtime.
RUN useradd --create-home --shell /bin/bash hvac
USER hvac

# Default port Railway/Fly override via $PORT. Our server honors it.
EXPOSE 8000

# Streamable-HTTP transport, binding 0.0.0.0 via server.py default.
ENTRYPOINT ["hvac-mcp"]
CMD ["--http"]
