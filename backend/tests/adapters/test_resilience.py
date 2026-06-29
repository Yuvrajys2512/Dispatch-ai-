"""Circuit breaker + fallback: a real-provider outage never strands a caller."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.adapters.base import AudioChunk, ExtractT, TranscriptChunk
from app.adapters.mock.asr import MockASRProvider
from app.adapters.mock.llm import MockLLMProvider
from app.adapters.mock.tts import MockTTSProvider
from app.adapters.resilience import (
    CircuitBreaker,
    ResilientASRProvider,
    ResilientLLMProvider,
    ResilientTTSProvider,
)
from app.domain.enums import Severity
from app.domain.models import IncidentCard
from tests.adapters.helpers import collect, text_audio_stream


class BoomLLM:
    """A real LLM that is always down (errors/times out)."""

    def __init__(self, *, sleep: float = 0.0) -> None:
        self.calls = 0
        self._sleep = sleep

    async def extract(self, prompt: str, schema: type[ExtractT]) -> ExtractT:
        self.calls += 1
        if self._sleep:
            await asyncio.sleep(self._sleep)
        raise RuntimeError("provider down")

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        self.calls += 1
        raise RuntimeError("provider down")
        yield  # pragma: no cover - makes this an async generator


class BoomASR:
    async def stream_transcribe(self, audio) -> AsyncIterator[TranscriptChunk]:
        raise RuntimeError("asr down")
        yield  # pragma: no cover


class BoomTTS:
    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        raise RuntimeError("tts down")
        yield  # pragma: no cover


def _breaker(threshold: int = 3, reset: float = 60.0) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=threshold, reset_seconds=reset, name="test")


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_mock_and_keeps_the_emergency():
    boom = BoomLLM()
    resilient = ResilientLLMProvider(
        breaker=_breaker(), timeout_s=1.0, real=boom, fallback=MockLLMProvider()
    )
    # A real outage must never drop a real emergency — the mock still classifies it.
    card = await resilient.extract(
        "Accident ho gaya, do log ghayal hain, khoon", IncidentCard
    )
    assert isinstance(card, IncidentCard)
    assert card.severity is Severity.CRITICAL
    assert boom.calls == 1  # the primary was tried once, then we fell back


@pytest.mark.asyncio
async def test_llm_timeout_trips_failure_and_falls_back():
    boom = BoomLLM(sleep=0.5)
    resilient = ResilientLLMProvider(
        breaker=_breaker(), timeout_s=0.01, real=boom, fallback=MockLLMProvider()
    )
    card = await resilient.extract("seene mein dard ho raha hai", IncidentCard)
    assert card.severity is Severity.HIGH  # mock fallback after the timeout


@pytest.mark.asyncio
async def test_breaker_opens_and_short_circuits_the_primary():
    boom = BoomLLM()
    resilient = ResilientLLMProvider(
        breaker=_breaker(threshold=2), timeout_s=1.0, real=boom, fallback=MockLLMProvider()
    )
    for _ in range(5):
        card = await resilient.extract("hahaha timepass", IncidentCard)
        assert isinstance(card, IncidentCard)  # always a valid card (fallback)
    # After 2 failures the breaker opened; further calls skip the dead primary.
    assert boom.calls == 2


@pytest.mark.asyncio
async def test_llm_generate_falls_back_to_mock():
    resilient = ResilientLLMProvider(
        breaker=_breaker(), timeout_s=1.0, real=BoomLLM(), fallback=MockLLMProvider()
    )
    tokens = await collect(resilient.generate(""))
    assert "112" in "".join(tokens)


@pytest.mark.asyncio
async def test_asr_failure_falls_back_to_mock():
    resilient = ResilientASRProvider(
        breaker=_breaker(), timeout_s=1.0, real=BoomASR(), fallback=MockASRProvider()
    )
    chunks = await collect(
        resilient.stream_transcribe(text_audio_stream("do log ghayal hain", asr_confidence=0.9))
    )
    assert any(c.is_final for c in chunks)
    assert chunks[-1].text == "do log ghayal hain"


@pytest.mark.asyncio
async def test_tts_failure_falls_back_to_mock():
    resilient = ResilientTTSProvider(
        breaker=_breaker(), timeout_s=1.0, real=BoomTTS(), fallback=MockTTSProvider()
    )
    frames = await collect(resilient.stream_synthesize("Aap line pe baney rahiye"))
    assert frames and frames[-1].is_last
