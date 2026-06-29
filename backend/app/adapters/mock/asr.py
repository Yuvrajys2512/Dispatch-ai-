"""Mock ASR provider — scripted text → timed partial→final transcript chunks.

Honors :class:`~app.adapters.base.ASRProvider`. It buffers incoming audio frames
into an utterance (until a frame with ``is_last``), then emits a couple of
*partial* hypotheses (growing word-prefixes, lower confidence) followed by the
*final* transcript — mirroring how a real streaming ASR behaves.

Confidence is taken from the frame's ``meta['asr_confidence']`` when the mock
telephony supplied one; otherwise it is derived heuristically from signal
quality (empty = silence, laughter markers = garbled, etc.).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator

from app.adapters.base import AudioChunk, TranscriptChunk

PARTIAL_DELAY_MS = 3
FINAL_DELAY_MS = 5
MAX_PARTIALS = 2


def _heuristic_confidence(text: str) -> float:
    t = text.lower()
    if not t.strip():
        return 0.2  # silence
    if "*" in t or "haha" in t:
        return 0.55  # laughter / garbled
    if "..." in t:
        return 0.7  # hesitant / code-switching
    return 0.9


def _partial_prefixes(words: list[str]) -> list[str]:
    """Up to MAX_PARTIALS growing prefixes (never the full utterance)."""
    n = len(words)
    if n <= 1:
        return []
    raw = {max(1, math.ceil(n * k / (MAX_PARTIALS + 1))) for k in range(1, MAX_PARTIALS + 1)}
    cuts = [c for c in sorted(raw) if c < n]
    return [" ".join(words[:c]) for c in cuts]


class MockASRProvider:
    async def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[TranscriptChunk]:
        words: list[str] = []
        async for chunk in audio:
            word = chunk.text.strip()
            if word:
                words.append(word)
            if not chunk.is_last:
                continue

            full = " ".join(words)
            final_conf = chunk.meta.get("asr_confidence")
            if final_conf is None:
                final_conf = _heuristic_confidence(full)

            for prefix in _partial_prefixes(words):
                await asyncio.sleep(PARTIAL_DELAY_MS / 1000)
                yield TranscriptChunk(
                    text=prefix,
                    is_final=False,
                    confidence=round(min(final_conf * 0.8, 0.99), 2),
                    t_ms=chunk.t_ms,
                )

            await asyncio.sleep(FINAL_DELAY_MS / 1000)
            yield TranscriptChunk(
                text=full,
                is_final=True,
                confidence=round(float(final_conf), 2),
                t_ms=chunk.t_ms,
            )
            words = []
