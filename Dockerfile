FROM ghcr.io/astral-sh/uv:python3.10-bookworm AS uv

WORKDIR /app

COPY uv.lock /app/
COPY pyproject.toml /app/
COPY README.md /app/
COPY .python-version /app/

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=README.md,target=README.md \
    --mount=type=bind,source=.python-version,target=.python-version \
    ["uv", "sync", "--frozen", "--no-dev", "--no-editable"]

ADD ./src/mcp_local_rag /app/mcp_local_rag

FROM python:3.10-slim-bookworm

WORKDIR /app

# Install system dependencies for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY --from=uv /app /app/
ENV PYTHONPATH=/app

ENTRYPOINT ["mcp-local-rag"]
