"""Session recorder — manages session folders, transcripts, and audio archival.

Each session gets a folder: sessions/YYYY-MM-DD_<room_id>/
Contains: transcript.md, session.json, audio/*.wav
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def _slugify(text: str, max_words: int = 4) -> str:
    """Create a filename-safe slug from text."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text.lower())
    words = text.split()[:max_words]
    return "_".join(words) if words else "response"


def _format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def _format_file_timestamp(seconds: float) -> str:
    """Format seconds as MMmSSs for filenames."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}m{s:02d}s"


class SessionRecorder:
    """Manages a single session's recordings and transcript."""

    def __init__(self, room_id: str, output_dir: str = "./sessions"):
        self.room_id = room_id
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.session_dir = Path(output_dir) / f"{today}_{room_id}"
        self.audio_dir = self.session_dir / "audio"
        self.transcript_path = self.session_dir / "transcript.md"
        self.metadata_path = self.session_dir / "session.json"
        self._seq = 0
        self._start_time: datetime | None = None
        self._time_offset: float = 0.0  # For rejoin — offset from previous session

        self._init_session()

    def _init_session(self) -> None:
        """Create session directory structure and initialize files."""
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        is_rejoin = self.transcript_path.exists()

        if is_rejoin:
            self._recover_state()
        else:
            self._write_transcript_header()
            self._write_metadata(is_new=True)

        self._start_time = datetime.now(timezone.utc)

        if is_rejoin:
            self._append_transcript_event("Agent reconnected (resuming)")
            self._update_metadata_rejoin()
        else:
            self._append_transcript_event("Session started")

    def _recover_state(self) -> None:
        """Parse existing transcript to recover sequence counter and time offset."""
        content = self.transcript_path.read_text()

        # Find last sequence number from audio filenames
        seq_matches = re.findall(r"(\d{3})_\d{2}m\d{2}s_", content)
        if seq_matches:
            self._seq = int(seq_matches[-1]) + 1

        # Find last timestamp [MM:SS]
        ts_matches = re.findall(r"\[(\d{2}):(\d{2})\]", content)
        if ts_matches:
            last_m, last_s = ts_matches[-1]
            self._time_offset = int(last_m) * 60 + int(last_s)

    def _elapsed(self) -> float:
        """Seconds since session start, plus any offset from rejoins."""
        if self._start_time is None:
            return self._time_offset
        delta = (datetime.now(timezone.utc) - self._start_time).total_seconds()
        return self._time_offset + delta

    def _write_transcript_header(self) -> None:
        """Write the initial transcript header."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        header = (
            f"# Podcast Transcript\n"
            f"**Room:** {self.room_id}\n"
            f"**Date:** {today}\n"
            f"**Agent:** AI Guest\n"
            f"\n---\n\n"
        )
        self.transcript_path.write_text(header)

    def _write_metadata(self, is_new: bool = True) -> None:
        """Write or update session.json."""
        now_iso = datetime.now(timezone.utc).isoformat()
        if is_new:
            metadata = {
                "room_id": self.room_id,
                "created_at": now_iso,
                "rejoins": [{"joined_at": now_iso, "left_at": None}],
            }
        else:
            metadata = self._load_metadata()
        self.metadata_path.write_text(json.dumps(metadata, indent=2))

    def _load_metadata(self) -> dict:
        """Load existing session.json."""
        if self.metadata_path.exists():
            return json.loads(self.metadata_path.read_text())
        return {"room_id": self.room_id, "rejoins": []}

    def _update_metadata_rejoin(self) -> None:
        """Add a rejoin entry to session.json."""
        metadata = self._load_metadata()
        # Close previous session
        if metadata["rejoins"] and metadata["rejoins"][-1]["left_at"] is None:
            metadata["rejoins"][-1]["left_at"] = datetime.now(timezone.utc).isoformat()
        metadata["rejoins"].append({
            "joined_at": datetime.now(timezone.utc).isoformat(),
            "left_at": None,
        })
        self.metadata_path.write_text(json.dumps(metadata, indent=2))

    def _append_transcript(self, text: str) -> None:
        """Append text to transcript file."""
        with open(self.transcript_path, "a") as f:
            f.write(text)

    def _append_transcript_event(self, event: str) -> None:
        """Append a timestamped event line."""
        ts = _format_timestamp(self._elapsed())
        if "disconnect" in event.lower():
            self._append_transcript(f"\n## [{ts}] ⚠️ {event}\n")
        elif "reconnect" in event.lower() or "resuming" in event.lower():
            self._append_transcript(f"\n## [{ts}] ✅ {event}\n")
        else:
            self._append_transcript(f"\n## [{ts}] {event}\n")

    def log_host_speech(self, text: str) -> None:
        """Log host's transcribed speech to the transcript."""
        ts = _format_timestamp(self._elapsed())
        self._append_transcript(f"\n## [{ts}] Host\n> {text}\n")

    def log_agent_response(self, text: str, audio_data: bytes | None = None) -> str | None:
        """Log agent's response and optionally save audio.

        Returns the audio filename if audio was saved, None otherwise.
        """
        elapsed = self._elapsed()
        ts = _format_timestamp(elapsed)
        audio_filename = None

        if audio_data is not None:
            slug = _slugify(text)
            file_ts = _format_file_timestamp(elapsed)
            audio_filename = f"{self._seq:03d}_{file_ts}_{slug}.wav"
            audio_path = self.audio_dir / audio_filename
            audio_path.write_bytes(audio_data)
            self._seq += 1
            self._append_transcript(f"\n## [{ts}] Agent → `{audio_filename}`\n> {text}\n")
        else:
            self._append_transcript(f"\n## [{ts}] Agent\n> {text}\n")

        return audio_filename

    def log_disconnect(self) -> None:
        """Log agent disconnection."""
        self._append_transcript_event("Agent disconnected")
        metadata = self._load_metadata()
        if metadata["rejoins"] and metadata["rejoins"][-1]["left_at"] is None:
            metadata["rejoins"][-1]["left_at"] = datetime.now(timezone.utc).isoformat()
            self.metadata_path.write_text(json.dumps(metadata, indent=2))

    def log_session_end(self) -> None:
        """Log session end."""
        self._append_transcript_event("Session ended")
        self.log_disconnect()
