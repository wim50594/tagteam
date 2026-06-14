FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Install uv (pinned for reproducible builds)
COPY --from=ghcr.io/astral-sh/uv:0.5.5 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first so this layer is cached independently of
# application code changes. pyproject.toml / uv.lock live alongside the
# application code in ./app.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Now copy the application code and finalise the environment.
COPY app .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

RUN mkdir -p /app/data/media

# Make the project's virtualenv the default Python.
ENV PATH="/app/.venv/bin:$PATH"

# App version, set from the release's git tag in CI (see release.yml).
# Defaults to "dev" for local builds without an explicit build-arg.
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]