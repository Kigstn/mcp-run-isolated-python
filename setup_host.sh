#!/bin/sh
# Run this ON THE DOCKER HOST (the machine running dockerd)
#
# Only needed on Ubuntu 23.10+, which sets kernel.apparmor_restrict_unprivileged_userns=1. That lets
# bubblewrap create a user namespace but gives it zero capabilities, so bwrap dies with
# "setting up uid map: Permission denied". Same thing the sandbox-runtime CI does, see
# https://github.com/anthropics/sandbox-runtime/blob/main/.github/workflows/integration-tests.yml
set -eu

echo "kernel.apparmor_restrict_unprivileged_userns = 0" | sudo tee /etc/sysctl.d/99-bwrap.conf >/dev/null
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
