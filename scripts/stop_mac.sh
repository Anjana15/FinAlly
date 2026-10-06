#!/usr/bin/env bash
# Stop FinAlly (macOS / Linux). Idempotent. Keeps the 'finally-data' volume,
# so your portfolio persists across restarts.
set -euo pipefail

CONTAINER="finally"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not on PATH." >&2
  exit 1
fi

if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Stopping container '$CONTAINER'..."
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  docker rm "$CONTAINER" >/dev/null 2>&1 || true
  echo "FinAlly stopped. Data volume 'finally-data' was kept."
else
  echo "FinAlly is not running."
fi
