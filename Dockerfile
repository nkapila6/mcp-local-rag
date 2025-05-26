# Taken reference from the following Dockerfile examples:
#  * UV Docker Example - https://github.com/astral-sh/uv-docker-example/blob/main/multistage.Dockerfile
#  * SQLite MCP Server Dockerfile - https://github.com/modelcontextprotocol/servers/blob/main/src/sqlite/Dockerfile

FROM ghcr.io/astral-sh/uv:0.7-python3.10-bookworm-slim AS builder

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Disable Python downloads, because we want to use the system interpreter
# across both images.
ENV UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
--mount=type=bind,source=uv.lock,target=uv.lock \
--mount=type=bind,source=pyproject.toml,target=pyproject.toml \
--mount=type=bind,source=.python-version,target=.python-version \
uv sync --frozen --no-install-project --no-dev --no-editable

COPY uv.lock /app
COPY pyproject.toml /app
COPY README.md /app
COPY .python-version /app
ADD ./src/mcp_local_rag /app/mcp_local_rag

RUN --mount=type=cache,target=/root/.cache/uv \
uv sync --locked --no-dev

# Then, use a final image without uv
FROM python:3.10-slim-bookworm

WORKDIR /app

# Install system dependencies for OpenCV + MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the application from the builder
COPY --from=builder --chown=app:app /app /app

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

ENTRYPOINT ["mcp-local-rag"]
