"""OpenAI-compatible Whisper STT API wrapper.

Wraps faster-whisper behind POST /v1/audio/transcriptions.
Run: uvicorn src.wrappers.whisper_api:app --port 8100
"""

from __future__ import annotations

import io
import os

import librosa
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("CLAWCAST_STT_MODEL", "small.en")

app = FastAPI(title="Clawcast Whisper STT")

model: WhisperModel | None = None


@app.on_event("startup")
async def load_model():
    global model
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: UploadFile = File(...),
    model_name: str = Form(default="whisper-1", alias="model"),
    language: str = Form(default="en"),
):
    audio_bytes = await file.read()
    buf = io.BytesIO(audio_bytes)

    # Load audio and resample to 16kHz (Whisper's expected rate).
    # LiveKit sends 48kHz — librosa handles the conversion.
    audio, _ = librosa.load(buf, sr=16000, mono=True)
    audio = audio.astype(np.float32)

    segments, _ = model.transcribe(audio, language=language, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments)

    return JSONResponse({"text": text})


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_SIZE}
