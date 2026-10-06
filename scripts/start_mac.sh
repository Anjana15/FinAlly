#!/usr/bin/env bash
# Start FinAlly in Docker (macOS / Linux). Idempotent: safe to run repeatedly.
#
# Usage: scripts/start_mac.sh [--build] [--no-open]
#   --build    rebuild the image even if it already exists
#   --no-open  don't open the browser
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT="${FINALLY_PORT:-8000}"
URL="http://localhost:${PORT}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BUILD=0
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --no-open) OPEN=0 ;;
    -h|--help)
      sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $arg (use --build, --no-open)" >&2; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not on PATH." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Error: the Docker daemon is not running (start Docker Desktop and retry)." >&2
  exit 1
fi

health_ok() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$URL/api/health" >/dev/null 2>&1
  else
    [ "$(docker container inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$CONTAINER" 2>/dev/null)" = "healthy" ]
  fi
}

open_browser() {
  [ "$OPEN" -eq 1 ] || return 0
  if command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 || true
  fi
}

# .env is required by `docker run --env-file`.
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "Notice: created .env from .env.example. Add your OPENROUTER_API_KEY to .env for AI chat"
    echo "        (or set LLM_MOCK=true), then restart: scripts/stop_mac.sh && scripts/start_mac.sh"
  else
    echo "Error: .env and .env.example are both missing." >&2
    exit 1
  fi
fi

# Build the image if it's missing or a rebuild was requested.
if [ "$BUILD" -eq 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Building image '$IMAGE'..."
  docker build -t "$IMAGE" .
  if [ "$BUILD" -eq 1 ] && docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "Replacing existing container with the new image..."
    docker rm -f "$CONTAINER" >/dev/null
  fi
fi

running="$(docker container inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [ "$running" = "true" ]; then
  echo "FinAlly is already running at $URL"
  open_browser
  exit 0
fi

# Remove a stale stopped container, if any.
if [ -n "$running" ]; then
  docker rm -f "$CONTAINER" >/dev/null
fi

echo "Starting container '$CONTAINER'..."
if ! docker run -d \
  --name "$CONTAINER" \
  -v "$VOLUME":/app/db \
  -p "$PORT":8000 \
  --env-file .env \
  "$IMAGE" >/dev/null; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  echo "Error: could not start the container. If port $PORT is already in use," >&2
  echo "       free it or pick another port: FINALLY_PORT=8001 $0" >&2
  exit 1
fi

printf "Waiting for the app to become healthy"
healthy=0
for _ in $(seq 1 60); do
  if health_ok; then
    healthy=1
    break
  fi
  if [ "$(docker container inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" != "true" ]; then
    break
  fi
  printf "."
  sleep 1
done
echo

if [ "$healthy" -ne 1 ]; then
  echo "Error: FinAlly did not become healthy. Recent logs:" >&2
  docker logs --tail 40 "$CONTAINER" >&2 || true
  exit 1
fi

echo "FinAlly is running at $URL"
open_browser
