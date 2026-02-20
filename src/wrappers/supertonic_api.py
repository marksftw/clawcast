"""OpenAI-compatible Supertonic TTS API wrapper.

Wraps Supertonic behind POST /v1/audio/speech.
Run: uvicorn src.wrappers.supertonic_api:app --port 8200
"""

from __future__ import annotations

import io
import threading
from collections import deque

import numpy as np
import scipy.io.wavfile
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from supertonic import TTS

app = FastAPI(title="Clawcast Supertonic TTS")

tts: TTS | None = None

# Cache recent audio for archival retrieval by the agent.
# Each entry: {"text": str, "wav_bytes": bytes}
_audio_cache: deque[dict] = deque(maxlen=64)
_cache_lock = threading.Lock()

# Map OpenAI-style voice names to Supertonic voice styles.
# Users can pass either the Supertonic name directly (M1, F3, etc.)
# or an OpenAI-style name which we map here.
VOICE_MAP = {
    "alloy": "M1",
    "echo": "M2",
    "fable": "M3",
    "onyx": "M4",
    "nova": "F1",
    "shimmer": "F2",
}

SAMPLE_RATE = 44100


@app.on_event("startup")
async def load_model():
    global tts
    tts = TTS()


@app.post("/v1/audio/speech")
async def synthesize(request: Request):
    body = await request.json()
    text = body.get("input", "")
    voice_param = body.get("voice", "M1")
    speed = float(body.get("speed", 1.2))

    # Resolve voice name
    voice_name = VOICE_MAP.get(voice_param, voice_param)
    style = tts.get_voice_style(voice_name)

    wav, duration = tts.synthesize(
        text, voice_style=style, speed=speed, total_steps=5, lang="en"
    )

    # wav is numpy array shape (1, num_samples) at 44100 Hz
    # Convert to int16 WAV bytes
    audio = wav.squeeze()
    if audio.dtype != np.int16:
        # Normalize float to int16 range
        audio = np.clip(audio, -1.0, 1.0)
        audio = (audio * 32767).astype(np.int16)

    buf = io.BytesIO()
    scipy.io.wavfile.write(buf, SAMPLE_RATE, audio)
    wav_bytes = buf.getvalue()

    # Cache for archival retrieval
    with _cache_lock:
        _audio_cache.append({"text": text, "wav_bytes": wav_bytes})

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Type": "audio/wav"},
    )


@app.post("/v1/audio/pop")
async def pop_audio():
    """Pop the oldest cached audio entry. Used by the agent for archival."""
    with _cache_lock:
        if _audio_cache:
            entry = _audio_cache.popleft()
            return Response(
                content=entry["wav_bytes"],
                media_type="audio/wav",
                headers={
                    "Content-Type": "audio/wav",
                    "X-Text": entry["text"][:200],
                },
            )
    return JSONResponse(status_code=204, content=None)


@app.get("/health")
async def health():
    return {"status": "ok"}
