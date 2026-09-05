# rupture deployment unit (ADR-0016): the locked uv environment plus the `rupture` CLI, and the
# HTTP service built on the same layers (ADR-0036).
#
# Two targets. The default (`runtime`) is the CLI image the job manifests use; `api` adds the port
# and the uvicorn command for the combined FastAPI service.
#
#   docker build -f infra/docker/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) -t rupture:dev .
#   docker run --rm rupture:dev rupture --version
#
#   docker build -f infra/docker/Dockerfile --target api -t rupture-api:dev .
#   docker run --rm -p 8000:8000 -e RUPTURE_API_KEYS=changeme rupture-api:dev
#   curl -s localhost:8000/health
#
# Not yet built anywhere (no Docker on the development machine, not wired in CI): reviewed by hand.
# Context ignores are in infra/docker/Dockerfile.dockerignore (BuildKit reads <Dockerfile>.dockerignore).
# The OpenQuake engine is NOT in this image; rupture drives the separate pinned image
# openquake/engine:3.26.2 through the docker CLI (ADR-0011), which needs a docker socket at run time.

ARG PYTHON_IMAGE=python:3.12-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.7

# ---------------------------------------------------------------- builder
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS builder

# git: the ETAS baseline is a pinned git dependency (ADR-0009); build tools for any sdist fallback.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
# Dependency layer first (cached until the lock changes); the project itself is installed below.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --locked --no-dev

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.title="rupture" \
      org.opencontainers.image.description="Open research on earthquake predictability: forecasting, scoring and cascade loss." \
      org.opencontainers.image.source="https://github.com/dizzy1900/rupture" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

# No docker CLI in the image: `rupture hazard ...` needs a host with docker (see
# docs/DEPLOYMENT.md); inside this image those verbs skip with a printed reason.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 rupture \
 && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin rupture

WORKDIR /app
COPY --from=builder --chown=rupture:rupture /app/.venv /app/.venv
COPY --chown=rupture:rupture src/ /app/src/
COPY --chown=rupture:rupture contracts/ /app/contracts/
COPY --chown=rupture:rupture data/regions/ /app/data/regions/
# Committed runtime inputs that the risk and aftershock surfaces read through RUPTURE_REPO_ROOT:
# the Gorkha FSP and the HAZUS/GSIM/exposure tables (tests/fixtures/risk/), and the two ComCat
# sequence slices with their ETAS fits (tests/fixtures/aftershock/). Without them
# `scenarios.builtin()` raises on every /v1/avoided-loss request and the aftershock surface loads
# no sequences. They live under tests/ because that is where the committed slices are (ADR-0028
# and docs/AFTERSHOCK.md limitation 11); moving them under src/rupture/*/data/ so the wheel
# carries them is the proper fix and belongs to the model owners, not to this Dockerfile.
COPY --chown=rupture:rupture tests/fixtures/risk/ /app/tests/fixtures/risk/
COPY --chown=rupture:rupture tests/fixtures/aftershock/ /app/tests/fixtures/aftershock/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RUPTURE_REPO_ROOT=/app \
    RUPTURE_GIT_SHA="${GIT_SHA}"

# Inputs and outputs live on mounted volumes, never in the image (ADR-0016).
VOLUME ["/app/data", "/app/baselines", "/app/reports"]

USER rupture
# No ENTRYPOINT: the job manifests pass the full argv (`rupture ...`) as the container command,
# and a deployer may wrap it in `sh -c '...'`.
CMD ["rupture", "--help"]

# ---------------------------------------------------------------- api
# The same runtime layers with a port and a server command. Nothing is installed here: `uvicorn`
# and `fastapi` are project dependencies, already in the venv above.
FROM runtime AS api

# One application, both surfaces (ADR-0036): /v1/avoided-loss and /aftershock/forecast, one
# /health, one X-API-Key scheme. RUPTURE_API_KEYS must be set or every authenticated route
# answers 503 -- the service refuses rather than running open.
EXPOSE 8000
ENV RUPTURE_SERVICE_PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "rupture.services.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
