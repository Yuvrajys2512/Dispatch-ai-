"""Mock TTS provider — text → a stream of synthetic audio frames.

Honors :class:`~app.adapters.base.TTSProvider`. Emits one frame per word with an
increasing ``t_ms``, marks the last frame ``is_last``, and logs the spoken text
so you can "hear" the AI in the logs during a mock call. The first frame is
emitted with minimal delay to mirror a streaming TTS's fast first byte.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.adapters.base import AudioChunk

logger = logging.getLogger("dispatch.tts")

FIRST_BYTE_DELAY_MS = 2
FRAME_DELAY_MS = 3


class MockTTSProvider:
    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        logger.info("TTS speak: %s", text)
        words = text.split()
        if not words:
            return
        t_ms = 0
        for i, word in enumerate(words):
            delay = FIRST_BYTE_DELAY_MS if i == 0 else FRAME_DELAY_MS
            await asyncio.sleep(delay / 1000)
            t_ms += delay
            yield AudioChunk.from_text(
                word, seq=i, t_ms=t_ms, is_last=(i == len(words) - 1)
            )
