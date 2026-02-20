#!/usr/bin/env bash
# Starts the Clawcast agent and connects to a room.
# Usage: ./scripts/start-agent.sh --room <name>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Forward LiveKit connection info via env vars
export LIVEKIT_URL="${CLAWCAST_LIVEKIT_URL:-ws://localhost:7880}"
export LIVEKIT_API_KEY="${CLAWCAST_LIVEKIT_API_KEY:-devkey}"
export LIVEKIT_API_SECRET="${CLAWCAST_LIVEKIT_API_SECRET:-secret}"

cd "$PROJECT_DIR"
exec python3 src/agent.py connect "$@"
