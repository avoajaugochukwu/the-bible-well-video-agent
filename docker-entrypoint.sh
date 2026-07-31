#!/bin/bash
# Starts the Python pipeline API on an internal-only port and the Next.js UI
# on Railway's public $PORT, side by side. The UI's server-side proxy reaches
# the API via PIPELINE_API_URL=http://localhost:$PIPELINE_PORT — set here,
# not as a Railway variable, since it's always localhost in this
# single-container setup. If either process dies, the container exits so
# Railway's restart policy brings both back up together rather than leaving
# a UI with a dead backend running.
set -e

PIPELINE_PORT="${PIPELINE_PORT:-8081}"
PORT="${PORT:-8080}"

PORT="$PIPELINE_PORT" python3 src/ingest_server.py &
PIPELINE_PID=$!

export PIPELINE_API_URL="http://localhost:$PIPELINE_PORT"
(cd web && npx next start -p "$PORT") &
NEXT_PID=$!

wait -n "$PIPELINE_PID" "$NEXT_PID"
EXIT_CODE=$?
kill "$PIPELINE_PID" "$NEXT_PID" 2>/dev/null
exit $EXIT_CODE
