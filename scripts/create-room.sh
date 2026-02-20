#!/usr/bin/env bash
# Creates a LiveKit room and generates a host join URL.
# Usage: ./scripts/create-room.sh <room-name>

set -euo pipefail

ROOM_NAME="${1:?Usage: $0 <room-name>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load config values — fall back to defaults
LIVEKIT_URL="${CLAWCAST_LIVEKIT_URL:-ws://localhost:7880}"
LIVEKIT_API_KEY="${CLAWCAST_LIVEKIT_API_KEY:-devkey}"
LIVEKIT_API_SECRET="${CLAWCAST_LIVEKIT_API_SECRET:-secret}"

python3 -c "
import asyncio
from livekit import api

async def main():
    lk = api.LiveKitAPI(
        url='${LIVEKIT_URL}'.replace('ws://', 'http://').replace('wss://', 'https://'),
        api_key='${LIVEKIT_API_KEY}',
        api_secret='${LIVEKIT_API_SECRET}',
    )

    # Create room
    room = await lk.room.create_room(api.CreateRoomRequest(name='${ROOM_NAME}'))
    print(f'Room created: {room.name}')

    # Generate host token
    token = api.AccessToken(
        api_key='${LIVEKIT_API_KEY}',
        api_secret='${LIVEKIT_API_SECRET}',
    )
    token.with_identity('host')
    token.with_name('Host')
    token.with_grants(api.VideoGrants(
        room_join=True,
        room='${ROOM_NAME}',
    ))
    jwt = token.to_jwt()

    # Build Meet URL
    lk_url = '${LIVEKIT_URL}'.replace('ws://', 'wss://').replace('http://', 'https://')
    meet_url = f'https://meet.livekit.io/custom?liveKitUrl={lk_url}&token={jwt}'

    print()
    print(f'Host join URL:')
    print(meet_url)
    print()
    print(f'To start the agent:')
    print(f'  ./scripts/start-agent.sh --room ${ROOM_NAME}')

asyncio.run(main())
"
