# syntax=docker/dockerfile:1

# ---- builder: resolve and install into a venv with uv ----------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN uv venv /app/.venv

# Install dependencies first (cached layer), then the package itself.
COPY pyproject.toml README.md ./
COPY tendwell ./tendwell
RUN uv pip install --no-cache ".[llm,context,prometheus]"

# ---- runtime: minimal, non-root --------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root user. The instant demo writes nothing; a writable data dir is created
# for configs that persist (it stays empty by default).
RUN groupadd --system tendwell \
    && useradd --system --gid tendwell --uid 10001 --home-dir /app tendwell

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY --from=builder /app/.venv /app/.venv
COPY tendwell ./tendwell
COPY examples ./examples
RUN mkdir -p /app/data && chown -R tendwell:tendwell /app

USER tendwell

# Default: the instant tier. Produces a real health report with no model and no
# network, then exits. Override the command to serve, or point at another config.
ENTRYPOINT ["tendwell"]
CMD ["run", "--config", "examples/demo-instant.yaml"]
