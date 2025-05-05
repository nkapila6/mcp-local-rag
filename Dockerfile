FROM ghcr.io/astral-sh/uv:latest AS uv

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

COPY --from=uv /app/.venv /app/.venv
COPY --from=uv /app /app/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

ENTRYPOINT [ "mcp-local-rag" ]
