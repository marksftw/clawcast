#!/usr/bin/env bash
# Starts the Clawcast agent and connects to a room.
# Usage: ./scripts/start-agent.sh --room <name>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

# Forward LiveKit connection info via env vars
export LIVEKIT_URL="${CLAWCAST_LIVEKIT_URL:-ws://localhost:7880}"
export LIVEKIT_API_KEY="${CLAWCAST_LIVEKIT_API_KEY:-devkey}"
export LIVEKIT_API_SECRET="${CLAWCAST_LIVEKIT_API_SECRET:-secret}"

cd "$PROJECT_DIR"
python3 src/agent.py connect "$@" >> "$LOG_DIR/agent.log" 2>&1 &
AGENT_PID=$!
echo $AGENT_PID > "$PROJECT_DIR/agent.pid"

sleep 1
if kill -0 "$AGENT_PID" 2>/dev/null; then
    echo "Agent started (PID $AGENT_PID, log: logs/agent.log)"
else
    echo "Agent failed to start. Check logs/agent.log"
    exit 1
fi
