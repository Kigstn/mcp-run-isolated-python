#!/bin/sh
# Lets people using the prebuilt image add packages without rebuilding:
#   docker run -e PYTHON_DEPENDENCIES="numpy pandas" ...
set -eu

if [ -n "${PYTHON_DEPENDENCIES:-}" ]; then
  echo "Installing extra python dependencies: ${PYTHON_DEPENDENCIES}"
  # shellcheck disable=SC2086 # deliberate: space separated list of packages
  uv pip install --python /sandbox/.venv/bin/python ${PYTHON_DEPENDENCIES}
fi

exec mcp-run-isolated-python \
  --path_to_python=/sandbox/.venv/bin/python \
  --user=nonroot \
  --mcp_host=0.0.0.0 \
  "$@"
