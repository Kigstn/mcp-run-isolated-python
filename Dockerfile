# Adapted from:
# - https://github.com/astral-sh/uv-docker-example/blob/main/standalone.Dockerfile

# Args to make versions configurable easily
ARG PYTHON_VERSION=3.13
ARG PYTHON_DEPENDENCIES=""

# ----------------------------
# Builder stage
# ----------------------------
FROM ghcr.io/astral-sh/uv:trixie-slim AS builder

# Setup uv environment variables
# Configure the Python directory so it is consistent
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python before the project for caching
RUN uv python install ${PYTHON_VERSION}

WORKDIR /code

# Install dependencies (without workspace code, for caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-editable --no-dev

# Copy project source
COPY . .

# Install project + deps into venv
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev

# now install the uv env that will be used by the code executor
WORKDIR /sandbox
RUN uv pip install ${PYTHON_DEPENDENCIES}


# ----------------------------
# Final stage
# ----------------------------
# Then, use a final image without uv, but with node
FROM node:trixie-slim
LABEL authors="daniel.j"

# install certs & required deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get install -y ripgrep socat bubblewrap \
    && rm -rf /var/lib/apt/lists/*

# install the srt sandbox
RUN npm install -g @anthropic-ai/sandbox-runtime

WORKDIR /code

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

# Copy the Python version
COPY --from=builder --chown=python:python /python /python

# Copy project (with venv)
COPY --from=builder --chown=nonroot:nonroot /code /code

# Place executables in the environment at the front of the path
ENV PATH="/code/.venv/bin:$PATH"

USER nonroot

# ----------------------------
# Setup the sandbox on the final image
COPY --from=builder --chown=nonroot:nonroot /sandbox /sandbox

# todo install python deps & uv env
# todo entrypoint
# todo create custom settings maybe?