# Clawcast v1 — AI Podcast Guest Bot
## Technical Specification v1.0

**Date:** 2026-02-19
**Authors:** Spec/QA agent + implementation lead
**Status:** LOCKED v1.0 — 2026-02-20

---

## 1. Overview

Clawcast is a tool that allows an AI agent to join a podcast as a real guest with bidirectional audio and video. The agent listens to the host and other guests via WebRTC, transcribes speech, generates a response via LLM, converts it to speech, and sends it back — all in real-time.

The system uses **LiveKit** (self-hosted) as the WebRTC platform. Phase 1 records sessions locally to MP4. Later phases add live streaming to **Restream** via RTMP for multistreaming to YouTube, Twitch, etc.

**End goal:** An OpenClaw skill on ClawHub that any agent can install and use.

---

## 2. Architecture

```
Phase 1 (Record):
┌──────────────────────────────────────────────────┐
│              LiveKit Server (self-hosted)          │
│              Docker (localhost or TLS)             │
│                                                    │
│  ┌──────────┐  WebRTC   ┌──────────────────────┐ │
│  │   Host   │◄────────►│    AI Guest Agent      │ │
│  │ (browser)│           │    (LiveKit Agents)    │ │
│  └──────────┘           │                        │ │
│  ┌──────────┐  WebRTC   │                        │ │
│  │ Guest(s) │◄────────►│                        │ │
│  │ (browser)│           │                        │ │
│  └──────────┘           │  Silero VAD            │ │
│                          │  → Whisper STT         │ │
│                          │  → LLM (configurable)  │ │
│                          │  → Supertonic TTS      │ │
│                          │  + Avatar video        │ │
│                          └──────────────────────┘ │
│                                                    │
│  ┌──────────────────────────────────────────────┐ │
│  │            LiveKit Egress                      │ │
│  │  Room composite → MP4 file (local recording)   │ │
│  └──────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘

Phase 3 (Live stream — same system, one config change):
┌──────────────────────────────────────────────────┐
│  LiveKit Egress                                    │
│  Room composite → RTMP → Restream → YouTube/etc.  │
└──────────────────────────────────────────────────┘
```

---

## 3. Key Design Decision: OpenAI-Compatible Wrappers

Instead of writing custom LiveKit Agents plugins for Whisper and Supertonic, we wrap them in thin **OpenAI-compatible API servers** and use LiveKit's existing `openai.STT(base_url=...)` and `openai.TTS(base_url=...)` plugins.

**Why:**
- Proven pattern (used by ShayneP/local-voice-ai)
- Way less custom code than writing LiveKit plugins
- Easy to swap providers later (just change base_url)
- LiveKit's OpenAI plugin already handles streaming, framing, WebRTC track management

```python
# This is all the agent code needs:
session = AgentSession(
    vad=silero.VAD.load(),
    stt=openai.STT(base_url="http://localhost:8100/v1"),      # local Whisper
    llm=openai.LLM(base_url="http://localhost:8080/v1",       # Maple proxy
                    model="gpt-oss-120b"),
    tts=openai.TTS(base_url="http://localhost:8200/v1"),       # local Supertonic
)
```

---

## 4. Components

### 4.1 LiveKit Server (Self-Hosted, Docker)

**What:** Open-source WebRTC SFU.

**Setup:** Use LiveKit's official `livekit-server generate` tool to create the Docker Compose stack. Generates: Caddy (auto-TLS), LiveKit, Redis, Egress configs.

**Requirements:**
- **Local testing:** No domain needed — `http://localhost:7880` works for dev/testing on the same machine
- **Remote access (host joins from different machine):** Domain name with DNS A record + TLS (Caddy auto-generates certs). This is a browser requirement — cameras/mics only work over HTTPS.
- Domain is TBD — not a Phase 1 blocker, only needed when host joins remotely
- Ports: 7880 (HTTP/WS), 7881 (WebRTC/TCP), 3478/UDP (TURN), 50000-60000/UDP (WebRTC media). Add 443/80 when using TLS.
- TURN is built into LiveKit (no separate Coturn needed)

**Resource budget (8 CPU / 32GB RAM VPS):**
| Component | CPU | RAM |
|-----------|-----|-----|
| LiveKit server | ~1 | ~512MB |
| Egress (room composite) | ~3 | ~2GB |
| Whisper STT (inference bursts) | ~1-2 | ~1GB |
| Supertonic TTS | ~1 | ~512MB |
| LLM | 0 (external via Maple) | 0 |
| **Total peak** | **~6-7** | **~4GB** |

Tight but workable for a single podcast session.

**Deliverable:** Docker Compose file (generated + customized).

### 4.2 Whisper STT API Wrapper

**What:** A thin FastAPI server wrapping faster-whisper behind an OpenAI-compatible `/v1/audio/transcriptions` endpoint.

**Spec:**
- Endpoint: `POST /v1/audio/transcriptions`
- Accepts: multipart form with audio file (WAV/PCM from LiveKit)
- Returns: JSON with `text` field (OpenAI Whisper API format)
- Note: LiveKit outputs 48kHz, Whisper expects 16kHz — wrapper handles resampling internally (implementation detail)
- Model: `small.en` loaded at startup (default)
- Fallback models: `base.en` or `tiny.en` if CPU contention with Egress makes `small.en` too slow
- Model is configurable in `clawcast.yaml` — manual change + restart if latency is observed during testing
- Port: 8100

**Reference:** ShayneP/local-voice-ai uses VoxBox for this. We do it lighter with FastAPI + faster-whisper directly (already installed).

**Deployment:** Bare uvicorn process managed by `start-infra.sh`/`stop.sh` (not Docker — saves resources).

**Deliverable:** `src/wrappers/whisper_api.py` — single file FastAPI app.

### 4.3 Supertonic TTS API Wrapper

**What:** A thin FastAPI server wrapping Supertonic behind an OpenAI-compatible `/v1/audio/speech` endpoint.

**Spec:**
- Endpoint: `POST /v1/audio/speech`
- Accepts: JSON with `input` (text), `voice` (optional, default M1), `speed` (optional, default 1.2)
- Returns: audio bytes (WAV, 44100 Hz)
- Port: 8200
- Note: Supertonic outputs 44.1kHz; LiveKit WebRTC audio tracks are 48kHz. LiveKit's OpenAI TTS plugin likely handles resampling transparently, but verify during implementation. Same category as the Whisper inbound resample.

**Deployment:** Bare uvicorn process managed by `start-infra.sh`/`stop.sh` (not Docker).

**Deliverable:** `src/wrappers/supertonic_api.py` — single file FastAPI app.

### 4.4 AI Guest Agent

**What:** A Python application using LiveKit Agents SDK that joins a LiveKit room as a participant.

**Pipeline:**
```
Host audio → Silero VAD → Whisper STT (via API) → LLM (via API) → Supertonic TTS (via API) → Audio track
                                                                                              → Video track (avatar)
```

**Participants:**
- **Phase 1:** 1:1 (host + agent) — get the pipeline working
- **Phase 1.5:** N participants (host + agent + 1-2 additional guests) — hard requirement, distinct milestone
- Multi-participant changes: speaker identification per track, transcript attribution by name, turn-taking logic (agent shouldn't jump in after every utterance — responds when addressed, when there's a group pause, or when asked a question), system prompt needs participant context

**Room Discovery (Phase 1):** Direct join via CLI argument. Simpler than the worker auto-dispatch model, which is designed for auto-scaling SaaS — overkill for a self-hosted tool.

Flow:
1. `./scripts/start-infra.sh` starts LiveKit server and API wrappers
2. `./scripts/create-room.sh` creates a room → outputs host join URL (with token)
3. `./scripts/start-agent.sh --room my-podcast-001` launches the agent into that specific room
4. Host opens join URL in browser

**Behavior (Phase 1 — 1:1):**
- Joins specified room via CLI arg (`--room`)
- Subscribes to host's audio track
- Silero VAD detects speech boundaries
- Transcribes via Whisper wrapper
- Sends transcript + system prompt + conversation history to LLM
- Publishes TTS audio as agent's audio track
- Publishes avatar as agent's video track
- Handles interruptions with configurable thresholds:
  - `interrupt_min_duration`: host must speak for N seconds during agent response before it's treated as an interruption (prevents coughs, "uh huh", etc.)
  - `silence_threshold`: how long host must be quiet before agent starts responding
  - `min_speech_duration`: minimum speech length to count as a real utterance

**System Prompt:** Configurable via `clawcast.yaml`. Default is conversational podcast guest persona.

**LLM:** Configurable — any OpenAI-compatible endpoint. Default: Maple proxy (`gpt-oss-120b`).

**LLM → TTS Buffering:** LiveKit's `AgentSession` has a built-in sentence tokenizer that handles this automatically. It buffers streaming LLM output and sends complete sentences to TTS, chunking on punctuation boundaries. No custom buffering logic needed — use the pipeline as designed. Result: first sentence plays while LLM is still generating the rest.

**Deliverable:** `src/agent.py`

### 4.5 Avatar (Video Track)

**MVP (Phase 1):**
- Canvas: full 720p (1280x720) video track
- Load static image (e.g., `avatar.png`)
- Avatar image scaled to ~400x400, centered on solid background (configurable color, default black)
- Leaves room around the avatar for Phase 4 pulsing rings/waveform without changing canvas size
- Create a `VideoSource`, publish as local video track
- Push static frames at 5-10fps (Egress encodes at 30fps regardless — duplicate frames, not a problem)

**Phase 4 — Visual Enhancement (Nice-to-Have):**
- Pulsing white rings emanating outward from avatar center when speaking
- OR: audio waveform visualization behind/around avatar
- Driven by TTS audio amplitude
- Smooth transition between speaking/silent states

**Implementation:** Pillow for frame generation. Read TTS audio amplitude for Phase 4 animation.

**Reference:** LiveKit `examples/avatar_agents/` for video track publishing pattern.

**Deliverable:** `src/avatar/static.py` (Phase 1), `src/avatar/animated.py` (Phase 4)

### 4.6 LiveKit Egress (Recording)

**What:** LiveKit Egress composites room participants and records to a local MP4 file.

**Phase 1 — Record to file:**
- Use **Room Composite** mode (captures entire room)
- Output: MP4 file saved to the session folder (see Section 5)
- Resolution: 1280x720 @ 30fps
- Audio: mixed (host + agent)
- Layout: LiveKit built-in `grid` or `speaker` layout (custom template not needed for MVP)

**Phase 3 — Live stream (future):**
- Same Egress, switch output from file to RTMP
- Point at Restream's RTMP ingest URL
- Add custom layout template if needed for branding
- One config change, no code changes

**Deliverable:** Egress config for file recording. Recording saved alongside session transcript.

### 4.7 Host Web UI

**What:** The web page the host opens in their browser to join the LiveKit room with camera + mic.

**Approach:** Use LiveKit's open-source **Meet** example app (https://github.com/livekit-examples/meet). Ready-made Next.js app with camera/mic selection, room joining, and participant display.

**Phase 1:** Use LiveKit's hosted Meet at `meet.livekit.io` — no self-hosting needed for dev/testing. `create-room.sh` outputs a URL like `https://meet.livekit.io/custom?liveKitUrl=...&token=...`. Host clicks it, they're in.

**Phase 5 (Skill Packaging):** Self-host Meet app for a fully self-contained deployment.

**Deliverable:** Phase 1: `create-room.sh` generates correct Meet URL. Phase 5: Meet app deployment config.

---

## 5. Session Recording & Transcript

### 5.1 Session Folder

Each stream session gets its own folder under `sessions/`:

```
sessions/
└── 2026-02-19_a1b2c3d4/
    ├── transcript.md
    ├── audio/
    │   ├── 000_00m00s_hello.wav
    │   ├── 001_02m15s_response.wav
    │   └── 002_05m42s_followup.wav
    └── session.json
```

**Folder naming:** `YYYY-MM-DD_<room_id>` where `room_id` is the LiveKit room name/ID (unique per room creation). This is better than URL-based because:
- LiveKit room IDs are unique per session
- The host may reuse the same LiveKit URL pattern across different streams
- If the agent disconnects and rejoins the same room, the room ID stays the same → same folder

**`session.json`** stores metadata:
```json
{
  "room_id": "a1b2c3d4",
  "room_url": "https://your-domain.com/room/a1b2c3d4",
  "created_at": "2026-02-19T21:30:00Z",
  "rejoins": [
    { "joined_at": "2026-02-19T21:30:00Z", "left_at": null }  // Updated to ISO timestamp on disconnect/leave
  ]
}
```

### 5.2 Audio Archive

Every TTS audio file the agent generates and sends to the stream is saved in the `audio/` subfolder.

**Naming convention:** `{sequence}_{timestamp}_{slug}.wav`
- `sequence`: zero-padded 3-digit counter (000, 001, 002...)
- `timestamp`: session-relative time in `MMmSSs` format (e.g., `02m15s`)
- `slug`: first few words of the response, slugified (for human browsability)

### 5.3 Transcript (Markdown)

A single `transcript.md` file is maintained throughout the session. Updated in real-time as exchanges happen.

**Format:**
```markdown
# Podcast Transcript
**Room:** a1b2c3d4
**Date:** 2026-02-19
**Agent:** AI Guest

---

## [00:00] Session started

## [00:12] Host
> Hey, welcome to the show! Tell us a bit about yourself.

## [00:18] Agent → `000_00m18s_intro.wav`
> Thanks for having me! I'm an AI agent that lives on the internet
> and builds things. I'm really into privacy tech and encrypted AI.

## [02:15] Guest
> That's fascinating. How does encrypted AI actually work?

## [02:22] Agent → `001_02m22s_encrypted_ai.wav`
> Great question. The short version is that your data gets encrypted
> before it ever reaches the AI model...

## [15:30] ⚠️ Agent disconnected

## [15:45] ✅ Agent reconnected (resuming from 15:30)

## [15:52] Host
> Looks like you're back! As I was saying...
```

**Timestamp behavior:**
- Time starts at `00:00` when the agent first joins
- If the agent disconnects and rejoins the same room, it reads the last timestamp from the transcript and continues incrementing from there
- Disconnection and reconnection events are logged

**What gets logged:**
| Event | Logged? |
|-------|---------|
| Agent joins/rejoins | ✅ with timestamp |
| Host speech (transcribed) | ✅ with timestamp and quoted text |
| Guest speech (transcribed) | ✅ with timestamp, speaker label, and quoted text (Phase 1.5) |
| Agent response (text) | ✅ with timestamp, text, and audio filename |
| Agent disconnect/reconnect | ✅ with timestamp |
| Agent leaves (session end) | ✅ with timestamp |

---

## 6. Testing (Phase 1 — SSH Tunnel)

Since the host (local machine) and server (VPS) are on different machines, and we don't have a domain yet for TLS, use an SSH tunnel for Phase 1 testing. The browser sees `localhost` and allows camera/mic access without HTTPS.

```bash
# From Mac — forward LiveKit ports through SSH
ssh -L 7880:localhost:7880 -L 7881:localhost:7881 root@YOUR_VPS_IP
# Note: Only TCP ports are tunneled. UDP ports (3478, 50000-60000) are NOT forwarded.
# WebRTC media falls back to TCP via port 7881 — functional but higher latency.
```

Then open `http://localhost:7880` in Chrome on Mac to join the LiveKit room. The browser thinks it's local → getUserMedia works → full conversation with the agent.

**⚠️ Caveat:** WebRTC media (UDP) will likely NOT tunnel over SSH. LiveKit falls back to TCP (port 7881, which is tunneled), but expect added latency. SSH tunnel is good enough for verifying the pipeline works end-to-end, but for real conversation testing with natural cadence, set up domain + TLS as a fast follow. Don't block Phase 1 development on it, but plan to have it ready before serious testing.

---

## 7. User Flow

### Host (Podcast Operator):
1. Run `./scripts/start-infra.sh` — starts LiveKit server, Redis, Egress (Docker Compose) + Whisper/Supertonic wrappers (uvicorn, PID files). Runs in background.
2. Run `./scripts/create-room.sh my-podcast-001` — creates room, generates JWT token, outputs host join URL
3. Run `./scripts/start-agent.sh --room my-podcast-001` — launches agent into the room
4. Open host join URL in browser (LiveKit Meet app with token in query param)
5. Join with webcam + mic
6. AI agent is already in the room, says hello
7. Have the conversation (Egress records to MP4 in session folder)
8. Run `./scripts/stop.sh` — kills agent + wrappers (via PID files), runs `docker-compose down` (stops everything from both scripts)

### AI Agent (Automated):
1. Joins specified room via `--room` CLI arg
2. Subscribes to host's audio track
3. Waits for host to speak
4. Transcribe → LLM → TTS → publish audio + avatar video
5. Handles interruptions per configured thresholds
6. Logs all exchanges to session transcript
7. Saves all TTS audio files to session folder
8. Continues until room closes or stop signal

---

## 8. Configuration

```yaml
# clawcast.yaml
livekit:
  url: "ws://localhost:7880"            # wss:// when using TLS + domain
  api_key: "your-api-key"              # Generated by `livekit-server generate`
  api_secret: "your-api-secret"        # All values can be overridden via env vars:
                                        # CLAWCAST_LIVEKIT_API_KEY, CLAWCAST_LIVEKIT_API_SECRET, etc.

agent:
  name: "YourAgentName"
  system_prompt: |
    You are an AI podcast guest. You're knowledgeable about 
    AI, privacy, Bitcoin, and technology. Keep responses concise 
    (2-3 sentences). Be conversational and witty. Ask follow-up 
    questions when appropriate.
  avatar: "./assets/avatar.png"
  avatar_bg_color: "#000000"

llm:
  base_url: "http://localhost:8080/v1"  # Maple proxy
  api_key: "your-api-key-here"          # "not-needed" for local Maple; actual key required for cloud providers (OpenAI, Anthropic)
  model: "gpt-oss-120b"
  temperature: 0.7                      # Lower = calmer, higher = more energetic
  max_tokens: 200                       # Keep responses concise for podcast cadence

stt:
  base_url: "http://localhost:8100/v1"  # Local Whisper wrapper
  model: "small.en"                     # Options: tiny.en, base.en, small.en

tts:
  base_url: "http://localhost:8200/v1"  # Local Supertonic wrapper
  voice: "M1"                           # Options: F1-F5, M1-M5
  speed: 1.2                            # 0.5 = slow, 1.0 = normal, 2.0 = fast

vad:
  min_speech_duration: 0.5              # Seconds host must speak before agent considers it speech
  silence_threshold: 1.0                # Seconds of silence before agent starts responding
  interrupt_min_duration: 1.5           # Seconds host must speak during agent response to trigger interruption
                                        # (prevents coughs / "uh huh" from cutting off the agent)

egress:
  mode: "record"                    # "record" (Phase 1) or "stream" (Phase 3)
  output_dir: "./sessions"          # Where recordings are saved
  layout: "grid"                    # Built-in: grid, speaker, single-speaker
  resolution: "1280x720"
  # Phase 3 (live streaming):
  # rtmp_url: "rtmp://live.restream.io/live/YOUR_STREAM_KEY"
```

---

## 9. Directory Structure

```
clawcast/
├── SKILL.md                        # OpenClaw skill definition
├── clawcast.example.yaml           # Config template with placeholder values (checked into git)
├── clawcast.yaml                   # Real config with secrets (.gitignore'd)
├── .gitignore                      # Ignores clawcast.yaml, sessions/
├── requirements.txt                # Python dependencies
├── setup.sh                        # One-command setup
├── docker-compose.yml              # LiveKit + Redis + Egress
├── src/
│   ├── agent.py                    # Main agent entrypoint
│   ├── config.py                   # Config loader
│   ├── session_recorder.py         # Session folder, transcript, audio archival
│   ├── wrappers/
│   │   ├── whisper_api.py          # FastAPI Whisper → OpenAI-compatible
│   │   └── supertonic_api.py       # FastAPI Supertonic → OpenAI-compatible
│   └── avatar/
│       ├── static.py               # Static image video track
│       └── animated.py             # (Phase 4) Pulsing rings / waveform
├── sessions/                       # Auto-created per stream
│   └── 2026-02-19_a1b2c3d4/       # Example session
│       ├── transcript.md           # Full exchange log
│       ├── session.json            # Session metadata
│       └── audio/                  # All TTS audio files
│           └── 000_00m18s_intro.wav
├── templates/
│   └── podcast-layout/             # Custom Egress layout template (Phase 3, see Section 12)
├── assets/
│   └── avatar.png      # Default avatar
├── scripts/
│   ├── start-infra.sh              # Start infra (docker-compose up) + wrappers (uvicorn, writes PID files)
│   ├── start-agent.sh              # Start agent into specified room (--room)
│   ├── stop.sh                     # Kill agent + wrappers via PID files, docker-compose down
│   ├── create-room.sh             # Creates LiveKit room, generates JWT, outputs host join URL
│   └── cleanup.sh                 # Lists sessions with size/date, interactive delete by age or name
└── tests/
    ├── test_whisper_api.py         # Whisper wrapper tests
    ├── test_supertonic_api.py      # Supertonic wrapper tests
    ├── test_session_recorder.py    # Session recording tests
    └── test_agent.py               # Agent integration tests
```

---

## 10. Reference Projects

Study these before implementation:

| Project | URL | What to Learn |
|---------|-----|---------------|
| **ShayneP/local-voice-ai** | https://github.com/ShayneP/local-voice-ai | Docker Compose wiring, OpenAI-compatible local inference pattern |
| **ringbot** (OpenClaw skill) | https://github.com/openclaw/skills/tree/main/skills/ringbot | LiveKit + STT→LLM→TTS pipeline in an OpenClaw skill |
| **LiveKit voice_agents examples** | https://github.com/livekit/agents/examples/voice_agents/ | Full pipeline, AgentSession, interruption handling, Silero VAD |
| **LiveKit avatar_agents examples** | https://github.com/livekit/agents/examples/avatar_agents/ | Publishing video tracks alongside audio |
| **LiveKit egress template** | https://github.com/livekit/egress/template-default/ | Custom React/HTML layout for room composite |
| **discord-voice** (OpenClaw skill) | https://github.com/openclaw/skills/discord-voice | VAD settings, barge-in, interruption handling patterns |

---

## 11. Dependencies

### System
- Docker + Docker Compose
- Python 3.10+
- Domain name with DNS (for remote access — not required for Phase 1 dev/testing)

### Python Packages
- `livekit-agents` — LiveKit Agents SDK
- `livekit-plugins-openai` — LLM/STT/TTS via OpenAI-compatible APIs
- `livekit-plugins-silero` — VAD
- `faster-whisper` — Local STT (for wrapper)
- `supertonic` — Local TTS (for wrapper)
- `fastapi` + `uvicorn` — API wrappers
- `Pillow` — Avatar image processing
- `numpy` — Audio amplitude for Phase 4 animation
- `pyyaml` — Config parsing
- `livekit-api` — LiveKit server SDK (for `create-room.sh` token generation)

### CLI Tools
- `lk` — LiveKit CLI (alternative for room/token management, optional)

### Docker Containers
- `livekit/livekit-server` — WebRTC SFU
- `livekit/egress` — Room composite → RTMP
- `redis` — Required by LiveKit + Egress

---

## 12. Implementation Phases

### Phase 1: Foundation (MVP)
- [ ] Generate LiveKit Docker Compose stack (`livekit-server generate`)
- [ ] Get LiveKit server running (localhost for dev; domain + TLS is a fast follow, not a blocker)
- [ ] Build Whisper API wrapper (`whisper_api.py`)
- [ ] Build Supertonic API wrapper (`supertonic_api.py`)
- [ ] Build basic agent using `AgentSession` + `openai.*` plugins pointed at local wrappers
- [ ] Static avatar image as video track (Pillow frame generator)
- [ ] Session recorder: folder creation, audio archival, transcript.md maintenance
- [ ] Rejoin handling: detect existing session folder, resume timestamps
- [ ] Egress recording to MP4 per session (saved in session folder)
- [ ] Test: Host joins room in browser, has conversation with agent
- [ ] Config file support (`clawcast.yaml`)
- [ ] Scripts: `start-infra.sh`, `start-agent.sh`, `stop.sh`, `create-room.sh`, `cleanup.sh`

### Phase 1.5: Multi-Participant Support
- [ ] Subscribe to all audio tracks in room (per-participant)
- [ ] Speaker identification via LiveKit participant identity
- [ ] Transcript labels each speaker by name (not just "Host")
- [ ] Turn-taking logic: agent responds when addressed, on group pauses, or when asked a question — NOT after every utterance
- [ ] System prompt includes participant names and roles
- [ ] Test with host + agent + 1-2 guests

### Phase 2: Polish & Hardening
- [ ] Tune interruption handling for podcast cadence
- [ ] Graceful error handling (LLM timeout, TTS failure, reconnect)

**Note on context window:** A 60-minute podcast generates ~6K tokens (~100 tokens/min at 150 words/min, ~1.5 words/token). With gpt-oss-120b's massive context window, full conversation history is sent with every request — no optimization needed. **Phase 2 note:** If supporting other LLMs with smaller context windows (e.g., GPT-4 8K-128K), research sliding window vs periodic summarization. Not a concern for Maple.
- [ ] Session stability: 60+ minutes without crash
- [ ] Domain + TLS setup for remote host access (may happen during Phase 1 testing — listed here as it's not a Phase 1 blocker)

### Phase 3: Live Streaming
- [ ] Egress switch from file recording to RTMP output
- [ ] Restream integration (RTMP ingest URL)
- [ ] Custom Egress layout template for branding (if needed)
- [ ] Test full pipeline: LiveKit room → RTMP → Restream → YouTube

### Phase 4: Visual Enhancement
- [ ] Pulsing white rings animation when speaking
- [ ] OR: audio waveform visualization
- [ ] Smooth transitions between speaking/silent states

### Phase 5: Skill Packaging
- [ ] SKILL.md for OpenClaw
- [ ] `setup.sh` one-command install
- [ ] Documentation for ClawHub listing
- [ ] Test with multiple LLM providers (Maple, OpenAI, Anthropic)
- [ ] Test with remote host (not localhost)
- [ ] README with screenshots / demo video

---

## 13. Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Host speech → transcription | < 2s | Whisper small.en on CPU |
| Transcription → first TTS word | < 2s | LLM generation + TTS start |
| Total response latency | < 4s | Acceptable for podcast conversation |
| Audio quality | 44.1kHz, clear | Supertonic M1 |
| Video output | 720p @ 30fps | For RTMP egress |
| Session stability | 60+ min | No crashes or memory leaks |
| Viewer stream delay | 2-5s | RTMP to Restream (Phase 3) |

---

## 14. Open Questions (Resolved)

| Question | Answer |
|----------|--------|
| Custom Whisper plugin? | No — wrap in OpenAI-compatible API, use `openai.STT` |
| Custom Supertonic plugin? | No — wrap in OpenAI-compatible API, use `openai.TTS` |
| Which VAD? | Silero (official LiveKit plugin, well-tested) |
| Egress layout? | Fully customizable via React/HTML templates |
| TURN server? | Built into LiveKit, auto-configured with Caddy |
| Host web UI? | LiveKit Meet (hosted for Phase 1, self-hosted for Phase 5) |

---

## 15. Success Criteria

**MVP is done when:**
- Host can open a browser, join a LiveKit room, and have a live conversation with the AI agent
- Agent uses local Whisper (STT), Maple (LLM), and Supertonic (TTS) — no cloud AI dependencies
- Agent displays a static avatar image as its video track
- The system runs stable for at least 30 minutes
- Egress records the full session to MP4 (composed layout, host + agent audio)

**Live streaming is done when:**
- The conversation streams to Restream via RTMP
- Viewers on YouTube/Twitch see host webcam + agent avatar

**Skill is done when:**
- Another OpenClaw user can install the skill, configure their own LLM/avatar/Restream, and get it running

---

*Spec locked v1.0 on 2026-02-20 after 4 review passes (2 human, 2 agent). Update only for implementation-discovered constraints.*
*Reference research: life/projects/clawcast/research/*.md*
