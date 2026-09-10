# Adapted from:
# - https://github.com/astral-sh/uv-docker-example/blob/main/standalone.Dockerfile

# Args to make configurable easily
ARG ENVIROMENT="trixie-slim"

# ----------------------------
# Builder stage
# ----------------------------
FROM ghcr.io/astral-sh/uv:${ENVIROMENT} AS builder

# Args to make configurable easily
ARG PYTHON_VERSION="3.13"
ARG PYTHON_DEPENDENCIES="pydantic"

# Setup uv environment variables
# Configure the Python directory so it is consistent
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_INSTALL_DIR=/python
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python before the project for caching
RUN uv python install ${PYTHON_VERSION}

# Install the custom uv environment that will be used by the code executor
WORKDIR /sandbox
RUN uv venv --python ${PYTHON_VERSION}
RUN uv pip install ${PYTHON_DEPENDENCIES}

# Copy project source
WORKDIR /code
COPY . .

# make sure the srt default config has the `enableWeakerNestedSandbox` set to true (needed for docker)
RUN sed -i 's/"enableWeakerNestedSandbox": *false/"enableWeakerNestedSandbox": true/' ./default_srt_settings.json

# Install project + deps into venv
RUN uv sync --frozen --no-editable --no-dev

# ----------------------------
# Final stage
# ----------------------------
# Then, use a final image without uv, but with node
FROM node:${ENVIROMENT}
LABEL authors="daniel.j"

# install certs & required deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get install -y ripgrep socat bubblewrap \
    && rm -rf /var/lib/apt/lists/*

# install the srt sandbox
RUN npm install -g @anthropic-ai/sandbox-runtime@'<=0.0.64'

WORKDIR /code

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

# Copy the Python version
COPY --from=builder --chown=python:python /python /python

# Copy project (with venv)
COPY --from=builder --chown=nonroot:nonroot /code /code

# Copy Sandbox
COPY --from=builder --chown=nonroot:nonroot /sandbox /sandbox

# Place executables in the environment at the front of the path
ENV PATH="/code/.venv/bin:$PATH"

EXPOSE 6400

ENTRYPOINT ["mcp-run-isolated-python", "--path_to_python=/sandbox/.venv/bin/python", "--user=nonroot", "--mcp_host=0.0.0.0"]