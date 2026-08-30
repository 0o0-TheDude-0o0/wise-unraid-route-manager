#!/bin/sh
set -eu

image=${1:-localhost/wise-route-manager:test}
if [ "${WISE_SMOKE_BUILD:-0}" = "1" ]; then
  podman build --format docker --tag "$image" --file Containerfile .
fi
exec podman run --rm --entrypoint /app/container/smoke.sh "$image"
