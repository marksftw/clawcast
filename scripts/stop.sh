#!/usr/bin/env bash
# Stops all Clawcast services: wrappers (via PID files) and Docker services.
# Usage: ./scripts/stop.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Kill wrapper processes via PID files
for pidfile in whisper.pid supertonic.pid; do
    if [ -f "$PROJECT_DIR/$pidfile" ]; then
        pid=$(cat "$PROJECT_DIR/$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "==> Stopping $pidfile (PID $pid)..."
            kill "$pid"
        else
            echo "==> $pidfile: process $pid already stopped."
        fi
        rm -f "$PROJECT_DIR/$pidfile"
    fi
done

echo "==> Stopping Docker services..."
docker compose down

echo "All services stopped."
