# Clawcast

AI agent that joins a LiveKit room as a podcast guest with bidirectional audio and video.

Uses local Whisper (STT), a configurable LLM, and Supertonic (TTS) — no cloud AI dependencies.

## Prerequisites

- Docker + Docker Compose
- Python 3.10+
- Dependencies: `pip install -r requirements.txt`

## Quick Start

```bash
# 1. Configure
cp clawcast.example.yaml clawcast.yaml
# Edit clawcast.yaml with your API keys

# 2. Start infrastructure (LiveKit, Redis, Egress, STT/TTS wrappers)
./scripts/start-infra.sh

# 3. Create a room and get the host join URL
./scripts/create-room.sh my-podcast-001

# 4. Start the agent
./scripts/start-agent.sh --room my-podcast-001

# 5. Open the host join URL in your browser, join with mic + camera

# 6. When done
./scripts/stop.sh
```

## Architecture

```
Host (browser) ←── WebRTC ──→ LiveKit Server ←── WebRTC ──→ AI Guest Agent
                                    │                         │
                                    │                    Silero VAD
                                Egress                   → Whisper STT (local)
                              (MP4 recording)            → LLM (configurable)
                                                         → Supertonic TTS (local)
                                                         + Avatar video track
```

The STT and TTS models run as local FastAPI servers behind OpenAI-compatible endpoints. The agent uses LiveKit's `openai.STT(base_url=...)` and `openai.TTS(base_url=...)` plugins to talk to them — no custom plugin code needed.

## Configuration

All config lives in `clawcast.yaml`. Every value can be overridden with `CLAWCAST_*` environment variables:

```
CLAWCAST_LIVEKIT_API_KEY=mykey
CLAWCAST_LIVEKIT_API_SECRET=mysecret
CLAWCAST_LLM_BASE_URL=http://localhost:8080/v1
```

See `clawcast.example.yaml` for all options.

## Session Recording

Each session creates a folder under `sessions/`:

```
sessions/2026-02-19_my-podcast-001/
├── transcript.md     # Timestamped conversation log
├── session.json      # Metadata (room ID, join/leave times)
└── audio/
    ├── 000_00m18s_intro.wav
    └── 001_02m22s_response.wav
```

Manage sessions with `./scripts/cleanup.sh`.

## Scripts

| Script | Purpose |
|--------|---------|
| `start-infra.sh` | Start Docker services + STT/TTS wrappers |
| `create-room.sh <name>` | Create LiveKit room, output host join URL |
| `start-agent.sh --room <name>` | Launch agent into a room |
| `stop.sh` | Stop everything |
| `cleanup.sh` | List/delete session recordings |

## Project Structure

```
src/
├── agent.py              # Main entrypoint (LiveKit AgentSession)
├── config.py             # YAML + env var config loader
├── session_recorder.py   # Transcript, audio archival, rejoin handling
├── wrappers/
│   ├── whisper_api.py    # OpenAI-compatible Whisper STT server
│   └── supertonic_api.py # OpenAI-compatible Supertonic TTS server
└── avatar/
    └── static.py         # Static avatar video track (720p, 5fps)
```
