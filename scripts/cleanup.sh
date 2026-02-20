#!/usr/bin/env bash
# Interactive session cleanup — lists sessions with size/date, allows deletion.
# Usage: ./scripts/cleanup.sh [--older-than DAYS]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SESSIONS_DIR="$PROJECT_DIR/sessions"

if [ ! -d "$SESSIONS_DIR" ]; then
    echo "No sessions directory found."
    exit 0
fi

OLDER_THAN=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --older-than)
            OLDER_THAN="$2"
            shift 2
            ;;
        *)
            echo "Usage: $0 [--older-than DAYS]"
            exit 1
            ;;
    esac
done

echo "Sessions:"
echo "========="
echo ""

total=0
for session in "$SESSIONS_DIR"/*/; do
    [ -d "$session" ] || continue
    name=$(basename "$session")
    size=$(du -sh "$session" 2>/dev/null | cut -f1)
    files=$(find "$session" -type f | wc -l | tr -d ' ')
    echo "  $name  ($size, $files files)"
    total=$((total + 1))
done

if [ "$total" -eq 0 ]; then
    echo "  (no sessions found)"
    exit 0
fi

echo ""
echo "Total: $total sessions"
echo ""

if [ -n "$OLDER_THAN" ]; then
    echo "Deleting sessions older than $OLDER_THAN days..."
    find "$SESSIONS_DIR" -maxdepth 1 -mindepth 1 -type d -mtime "+$OLDER_THAN" -exec rm -rf {} \;
    echo "Done."
else
    read -rp "Delete all sessions? [y/N] " confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        rm -rf "$SESSIONS_DIR"/*/
        echo "All sessions deleted."
    else
        echo "No sessions deleted."
    fi
fi
