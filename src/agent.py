"""Clawcast AI podcast guest agent.

Main entrypoint. Joins a LiveKit room, listens to host speech,
generates responses via LLM, and speaks back via TTS with avatar video.

Usage:
    python src/agent.py connect --room <name>
"""

from __future__ import annotations

import logging

import httpx
from livekit import agents, api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AgentServer,
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
)
from livekit.plugins import openai, silero

from src.avatar.static import publish_avatar
from src.config import load_config
from src.session_recorder import SessionRecorder

logger = logging.getLogger("clawcast")


class PodcastGuest(Agent):
    """The AI podcast guest agent."""

    def __init__(self, system_prompt: str) -> None:
        super().__init__(instructions=system_prompt)


server = AgentServer()
cfg = load_config()


@server.rtc_session(agent_name=cfg.agent.name)
async def entrypoint(ctx: agents.JobContext):
    room_name = ctx.room.name
    logger.info("Joining room: %s", room_name)

    # Initialize session recorder
    recorder = SessionRecorder(room_id=room_name, output_dir=cfg.egress.output_dir)

    # Publish avatar video track
    await publish_avatar(ctx.room, cfg.agent.avatar, cfg.agent.avatar_bg_color)
    logger.info("Avatar published")

    # Start egress recording (non-fatal if it fails)
    await _start_egress(room_name)

    # Build the voice pipeline
    session = AgentSession(
        vad=silero.VAD.load(
            min_speech_duration=cfg.vad.min_speech_duration,
            min_silence_duration=cfg.vad.silence_threshold,
        ),
        stt=openai.STT(
            model=cfg.stt.model,
            base_url=cfg.stt.base_url,
            api_key="local",
        ),
        llm=openai.LLM(
            model=cfg.llm.model,
            base_url=cfg.llm.base_url,
            api_key=cfg.llm.api_key,
            temperature=cfg.llm.temperature,
            max_completion_tokens=cfg.llm.max_tokens,
        ),
        tts=openai.TTS(
            model="tts-1",
            voice=cfg.tts.voice,
            speed=cfg.tts.speed,
            base_url=cfg.tts.base_url,
            api_key="local",
        ),
        min_interruption_duration=cfg.vad.interrupt_min_duration,
        min_endpointing_delay=cfg.vad.silence_threshold,
    )

    # Hook events for transcript logging
    @session.on("user_input_transcribed")
    def on_user_transcribed(event: UserInputTranscribedEvent):
        if event.is_final:
            logger.info("[Host] %s", event.transcript)
            recorder.log_host_speech(event.transcript)

    @session.on("conversation_item_added")
    async def on_item_added(event: ConversationItemAddedEvent):
        if event.item.role == "assistant":
            text = event.item.text_content
            if text:
                logger.info("[Agent] %s", text)
                audio_data = await _pop_tts_audio()
                recorder.log_agent_response(text, audio_data=audio_data)

    # Handle disconnection
    @ctx.room.on("disconnected")
    def on_disconnected(*args):
        logger.warning("Disconnected from room")
        recorder.log_disconnect()

    # Start the session
    await session.start(
        agent=PodcastGuest(cfg.agent.system_prompt),
        room=ctx.room,
    )

    # Greet the host
    await session.generate_reply(
        instructions="Greet the host warmly. Introduce yourself briefly and say you're excited to be on the show."
    )


async def _pop_tts_audio() -> bytes | None:
    """Pop cached TTS audio from the Supertonic wrapper for archival."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{cfg.tts.base_url.rstrip('/v1')}/v1/audio/pop")
            if resp.status_code == 200:
                return resp.content
    except Exception:
        logger.debug("Could not retrieve TTS audio for archival", exc_info=True)
    return None


async def _start_egress(room_name: str) -> None:
    """Start room composite egress for MP4 recording. Non-fatal on failure."""
    try:
        from livekit.protocol.egress import (
            EncodedFileOutput,
            EncodedFileType,
            RoomCompositeEgressRequest,
        )

        lk = api.LiveKitAPI(
            url=cfg.livekit.url.replace("ws://", "http://").replace("wss://", "https://"),
            api_key=cfg.livekit.api_key,
            api_secret=cfg.livekit.api_secret,
        )
        await lk.egress.start_room_composite_egress(
            RoomCompositeEgressRequest(
                room_name=room_name,
                layout=cfg.egress.layout,
                file_outputs=[
                    EncodedFileOutput(
                        file_type=EncodedFileType.MP4,
                        filepath=f"/out/{room_name}.mp4",
                    )
                ],
            )
        )
        logger.info("Egress recording started for room: %s", room_name)
    except Exception:
        logger.warning("Failed to start egress recording (non-fatal)", exc_info=True)


if __name__ == "__main__":
    agents.cli.run_app(server)
