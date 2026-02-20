"""Static avatar video track publisher.

Pre-renders a 1280x720 RGBA frame with a centered avatar image
on a configurable background color. Pushes at 5fps.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from livekit import rtc
from PIL import Image

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720
AVATAR_SIZE = 400
FPS = 5


def _hex_to_rgba(hex_color: str) -> tuple[int, int, int, int]:
    """Convert hex color string to RGBA tuple."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (r, g, b, 255)


def render_frame(avatar_path: str, bg_color: str = "#000000") -> bytes:
    """Render a single RGBA frame with the avatar centered on the background."""
    bg_rgba = _hex_to_rgba(bg_color)
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), bg_rgba)

    avatar_file = Path(avatar_path)
    if avatar_file.exists():
        avatar = Image.open(avatar_file).convert("RGBA")
        avatar = avatar.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        x = (CANVAS_WIDTH - AVATAR_SIZE) // 2
        y = (CANVAS_HEIGHT - AVATAR_SIZE) // 2
        canvas.paste(avatar, (x, y), avatar)

    return canvas.tobytes("raw", "RGBA")


async def publish_avatar(
    room: rtc.Room,
    avatar_path: str,
    bg_color: str = "#000000",
) -> rtc.VideoSource:
    """Publish a static avatar as a video track in the room.

    Returns the VideoSource for potential future animation use.
    """
    frame_data = render_frame(avatar_path, bg_color)

    source = rtc.VideoSource(CANVAS_WIDTH, CANVAS_HEIGHT)
    track = rtc.LocalVideoTrack.create_video_track("avatar", source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
    await room.local_participant.publish_track(track, options)

    frame = rtc.VideoFrame(
        CANVAS_WIDTH,
        CANVAS_HEIGHT,
        rtc.VideoBufferType.RGBA,
        frame_data,
    )

    async def _push_loop():
        while True:
            source.capture_frame(frame)
            await asyncio.sleep(1.0 / FPS)

    asyncio.create_task(_push_loop())
    return source
