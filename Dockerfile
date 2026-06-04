# syntax=docker/dockerfile:1
#
# Production image for the CivicVault Django web app.
#
# Multi-stage, uv-based. The web runtime deliberately EXCLUDES the heavy `ingest`
# dependency group (faster-whisper, ffmpeg-scale ML) — transcription/ingestion is
# an offline/local concern, not part of serving. psycopg[binary], boto3 (R2),
# whitenoise and gunicorn are all self-contained wheels, so the runtime stage
# needs no system packages.

ARG PYTHON_VERSION=3.12

# ---- Builder: resolve deps into a venv and collect static assets --------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

# uv binary, pinned by copying from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (cached layer) without the project itself.
# --no-dev and the default-group rules exclude both `dev` and `ingest`.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-dev --no-install-project

# Copy the application source and install the project into the venv.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Build the static manifest (content-hashed + compressed). DEBUG defaults to
# False, so this exercises WhiteNoise's CompressedManifestStaticFilesStorage and
# writes staticfiles/. collectstatic does not touch the database.
RUN /app/.venv/bin/python manage.py collectstatic --noinput

# ---- Runtime: minimal image with just the venv, app code, and static files ---
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# Run as an unprivileged user.
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid 1000 --no-create-home --home /app app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_SETTINGS_MODULE=civicvault.settings

WORKDIR /app

# Bring over the resolved venv, app source, and built static assets.
COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# Gunicorn serves WSGI; WhiteNoise (middleware) serves static assets in-process.
# --no-control-socket: we don't use the management interface, and its default
#   socket path isn't writable under a read-only root filesystem.
# --worker-tmp-dir /dev/shm: keep the worker heartbeat file on tmpfs (fast, and
#   writable when the root fs is read-only).
CMD ["gunicorn", "civicvault.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--no-control-socket", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
