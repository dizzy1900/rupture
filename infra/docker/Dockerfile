# rupture deployment unit (ADR-0016): the locked uv environment plus the `rupture` CLI.
# Build from the repository root:
#   docker build -f infra/docker/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) -t rupture:dev .
#   docker run --rm rupture:dev rupture --version
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
      org.opencontainers.image.description="Probabilistic seismic forecasting and cascade-loss model. rupture does not predict earthquakes." \
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

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    RUPTURE_GIT_SHA="${GIT_SHA}"

# Inputs and outputs live on mounted volumes, never in the image (ADR-0016).
VOLUME ["/app/data", "/app/baselines", "/app/reports"]

USER rupture
# No ENTRYPOINT: the job manifests pass the full argv (`rupture ...`) as the container command,
# and a deployer may wrap it in `sh -c '...'`.
CMD ["rupture", "--help"]
