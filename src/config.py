"""Clawcast configuration loader.

Loads from clawcast.yaml with CLAWCAST_* env var overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LiveKitConfig:
    url: str = "ws://localhost:7880"
    api_key: str = "devkey"
    api_secret: str = "secret"


@dataclass
class AgentConfig:
    name: str = "ClawcastAgent"
    system_prompt: str = (
        "You are an AI podcast guest. You're knowledgeable about "
        "AI, privacy, Bitcoin, and technology. Keep responses concise "
        "(2-3 sentences). Be conversational and witty. Ask follow-up "
        "questions when appropriate."
    )
    avatar: str = "./assets/avatar.png"
    avatar_bg_color: str = "#000000"


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:8080/v1"
    api_key: str = "not-needed"
    model: str = "gpt-oss-120b"
    temperature: float = 0.7
    max_tokens: int = 200


@dataclass
class STTConfig:
    base_url: str = "http://localhost:8100/v1"
    model: str = "small.en"


@dataclass
class TTSConfig:
    base_url: str = "http://localhost:8200/v1"
    voice: str = "M1"
    speed: float = 1.2


@dataclass
class VADConfig:
    min_speech_duration: float = 0.5
    silence_threshold: float = 1.0
    interrupt_min_duration: float = 1.5


@dataclass
class EgressConfig:
    mode: str = "record"
    output_dir: str = "./sessions"
    layout: str = "grid"
    resolution: str = "1280x720"


@dataclass
class ClawcastConfig:
    livekit: LiveKitConfig = field(default_factory=LiveKitConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    egress: EgressConfig = field(default_factory=EgressConfig)


# Maps section names to their dataclass types
_SECTION_CLASSES = {
    "livekit": LiveKitConfig,
    "agent": AgentConfig,
    "llm": LLMConfig,
    "stt": STTConfig,
    "tts": TTSConfig,
    "vad": VADConfig,
    "egress": EgressConfig,
}


def _apply_env_overrides(config: ClawcastConfig) -> None:
    """Override config values with CLAWCAST_* environment variables.

    Naming convention: CLAWCAST_<SECTION>_<KEY>
    e.g. CLAWCAST_LIVEKIT_API_KEY -> config.livekit.api_key
    """
    prefix = "CLAWCAST_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section_name, field_name = parts
        section = getattr(config, section_name, None)
        if section is None:
            continue
        if not hasattr(section, field_name):
            # Try joining remaining underscores (e.g. API_KEY -> api_key)
            # Already handled since we split on first _ only for section
            # but field names can have underscores. Re-parse with section known.
            remaining = key[len(prefix) + len(section_name) + 1:].lower()
            if not hasattr(section, remaining):
                continue
            field_name = remaining

        current = getattr(section, field_name)
        # Cast to the same type as the default
        if isinstance(current, bool):
            setattr(section, field_name, value.lower() in ("true", "1", "yes"))
        elif isinstance(current, int):
            setattr(section, field_name, int(value))
        elif isinstance(current, float):
            setattr(section, field_name, float(value))
        else:
            setattr(section, field_name, value)


def load_config(path: str | Path | None = None) -> ClawcastConfig:
    """Load config from YAML file with env var overrides.

    Search order for config file:
    1. Explicit path argument
    2. CLAWCAST_CONFIG env var
    3. ./clawcast.yaml (current directory)
    """
    if path is None:
        path = os.environ.get("CLAWCAST_CONFIG", "clawcast.yaml")
    path = Path(path)

    config = ClawcastConfig()

    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        for section_name, section_cls in _SECTION_CLASSES.items():
            if section_name in data and isinstance(data[section_name], dict):
                section_data = data[section_name]
                section = getattr(config, section_name)
                for k, v in section_data.items():
                    if hasattr(section, k):
                        setattr(section, k, v)

    _apply_env_overrides(config)
    return config
