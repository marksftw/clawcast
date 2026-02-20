#!/usr/bin/env bash
# Creates a LiveKit room and generates a host join URL.
# Usage: ./scripts/create-room.sh <room-name>

set -euo pipefail

ROOM_NAME="${1:?Usage: $0 <room-name>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Pass config via env vars to avoid shell injection in Python heredoc
export _LK_URL="${CLAWCAST_LIVEKIT_URL:-ws://localhost:7880}"
export _LK_API_KEY="${CLAWCAST_LIVEKIT_API_KEY:-devkey}"
export _LK_API_SECRET="${CLAWCAST_LIVEKIT_API_SECRET:-secret}"
export _LK_ROOM="$ROOM_NAME"

python3 -c "
import asyncio
import os
from livekit import api

async def main():
    lk_url = os.environ['_LK_URL']
    api_key = os.environ['_LK_API_KEY']
    api_secret = os.environ['_LK_API_SECRET']
    room_name = os.environ['_LK_ROOM']

    lk = api.LiveKitAPI(
        url=lk_url.replace('ws://', 'http://').replace('wss://', 'https://'),
        api_key=api_key,
        api_secret=api_secret,
    )

    # Create room
    room = await lk.room.create_room(api.CreateRoomRequest(name=room_name))
    print(f'Room created: {room.name}')

    # Generate host token
    token = api.AccessToken(api_key=api_key, api_secret=api_secret)
    token.with_identity('host')
    token.with_name('Host')
    token.with_grants(api.VideoGrants(room_join=True, room=room_name))
    jwt = token.to_jwt()

    # Build Meet URL
    ws_url = lk_url.replace('ws://', 'wss://').replace('http://', 'https://')
    meet_url = f'https://meet.livekit.io/custom?liveKitUrl={ws_url}&token={jwt}'

    print()
    print('Host join URL:')
    print(meet_url)
    print()
    print(f'To start the agent:')
    print(f'  ./scripts/start-agent.sh --room {room_name}')

asyncio.run(main())
"
