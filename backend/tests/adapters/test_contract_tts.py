"""TTS contract: streamed frames, increasing timing, faithful reconstruction."""

import pytest

from app.adapters.base import TTSProvider
from app.adapters.mock.tts import MockTTSProvider
from tests.adapters.helpers import collect


def test_mock_satisfies_protocol():
    assert isinstance(MockTTSProvider(), TTSProvider)


@pytest.mark.asyncio
async def test_synthesize_streams_frames_and_marks_last():
    tts = MockTTSProvider()
    text = "Aap line pe baney rahiye"
    frames = await collect(tts.stream_synthesize(text))

    assert len(frames) == len(text.split())
    assert frames[-1].is_last
    assert sum(1 for f in frames if f.is_last) == 1
    # Reconstructs the spoken text in order.
    assert " ".join(f.text for f in frames) == text
    # t_ms strictly increases (streaming/latency simulation).
    times = [f.t_ms for f in frames]
    assert times == sorted(times) and times[0] > 0


@pytest.mark.asyncio
async def test_empty_text_yields_no_frames():
    tts = MockTTSProvider()
    frames = await collect(tts.stream_synthesize("   "))
    assert frames == []
