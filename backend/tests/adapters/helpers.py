"""Shared helpers for adapter contract tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TypeVar

from app.adapters.base import AudioChunk

T = TypeVar("T")


async def text_audio_stream(
    text: str, *, asr_confidence: float | None = None
) -> AsyncIterator[AudioChunk]:
    """Yield one AudioChunk per word for a single utterance (last is is_last)."""
    words = text.split()
    if not words:
        yield AudioChunk.from_text("", is_last=True, asr_confidence=asr_confidence)
        return
    for i, word in enumerate(words):
        is_last = i == len(words) - 1
        yield AudioChunk.from_text(
            word,
            seq=i,
            t_ms=(i + 1) * 2,
            is_last=is_last,
            asr_confidence=asr_confidence if is_last else None,
        )


async def collect(aiter: AsyncIterator[T]) -> list[T]:
    return [item async for item in aiter]
