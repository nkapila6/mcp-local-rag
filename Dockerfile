# Taken reference from the following Dockerfile examples:
#  * UV Docker Example - https://github.com/astral-sh/uv-docker-example/blob/main/multistage.Dockerfile
#  * SQLite MCP Server Dockerfile - https://github.com/modelcontextprotocol/servers/blob/main/src/sqlite/Dockerfile

FROM ghcr.io/astral-sh/uv:0.13-trixie-slim AS builder

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# uv-managed python lives at a fixed path so the venv still resolves after
# both get copied into the distroless image
ENV UV_PYTHON_INSTALL_DIR=/python UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

COPY uv.lock pyproject.toml README.md .python-version /app/

RUN uv python install

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=/app/pyproject.toml \
    --mount=type=bind,source=uv.lock,target=/app/uv.lock \
    uv sync --frozen --no-install-project --no-dev --no-editable

COPY ./src/mcpsurfr /app/mcpsurfr

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Trim things we never load at runtime: test suites, type stubs, and stdlib
# modules that can't work without a display. The python binary is statically
# linked, so libpython.so is only for embedding, and the base interpreter's
# pip/setuptools are never used by the venv.
RUN find .venv/lib/python3.*/site-packages -type d \( -name tests -o -name test \) -prune -exec rm -rf {} + \
    && find .venv /python -name '*.pyi' -delete \
    && cd /python/cpython-* \
    && rm -rf include share lib/libpython3* lib/pkgconfig lib/tcl* lib/tk* lib/libtcl* lib/libtk* lib/itcl* lib/thread* lib/Tix* \
    && cd lib/python3.* \
    && rm -rf test idlelib tkinter turtledemo ensurepip lib2to3 site-packages/* lib-dynload/_tkinter*

# distroless/cc doesn't ship these: numpy needs libz, stdlib _crypt needs libcrypt
RUN mkdir /extra-libs \
    && cp -L /lib/$(uname -m)-linux-gnu/libz.so.1 /lib/$(uname -m)-linux-gnu/libcrypt.so.1 /extra-libs/

# distroless/cc has glibc, which is all the python build and numpy need
# (plus the two libs above). No shell, no package manager.
FROM gcr.io/distroless/cc-debian13:nonroot

# the MCP registry checks this matches "name" in server.json to verify we own the image
LABEL io.modelcontextprotocol.server.name="io.github.nkapila6/mcpsurfr"

WORKDIR /app

COPY --from=builder /python /python
COPY --from=builder /app /app
COPY --from=builder /extra-libs/ /usr/local/lib/

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    LD_LIBRARY_PATH=/usr/local/lib

ENTRYPOINT ["/app/.venv/bin/mcpsurfr"]
