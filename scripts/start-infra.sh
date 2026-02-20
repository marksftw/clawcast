#!/usr/bin/env bash
# Starts infrastructure: Docker services (LiveKit, Redis, Egress) and API wrappers.
# Usage: ./scripts/start-infra.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_DIR="$PROJECT_DIR"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

echo "==> Starting Docker services (LiveKit, Redis, Egress)..."
docker compose up -d

echo "==> Waiting for LiveKit to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:7880 > /dev/null 2>&1; then
        echo "    LiveKit ready."
        break
    fi
    sleep 1
done

echo "==> Starting Whisper STT wrapper on port 8100..."
uvicorn src.wrappers.whisper_api:app --host 0.0.0.0 --port 8100 \
    >> "$LOG_DIR/whisper.log" 2>&1 &
echo $! > "$PID_DIR/whisper.pid"
echo "    PID: $(cat "$PID_DIR/whisper.pid") (log: logs/whisper.log)"

echo "==> Starting Supertonic TTS wrapper on port 8200..."
uvicorn src.wrappers.supertonic_api:app --host 0.0.0.0 --port 8200 \
    >> "$LOG_DIR/supertonic.log" 2>&1 &
echo $! > "$PID_DIR/supertonic.pid"
echo "    PID: $(cat "$PID_DIR/supertonic.pid") (log: logs/supertonic.log)"

echo ""
echo "Infrastructure running. To stop: ./scripts/stop.sh"
