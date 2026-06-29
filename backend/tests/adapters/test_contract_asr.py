"""ASR contract: partial→final ordering, prefix growth, confidence ranges."""

import pytest

from app.adapters.base import ASRProvider
from app.adapters.mock.asr import MockASRProvider
from tests.adapters.helpers import collect, text_audio_stream


def test_mock_satisfies_protocol():
    assert isinstance(MockASRProvider(), ASRProvider)


@pytest.mark.asyncio
async def test_partials_precede_final_and_are_prefixes():
    asr = MockASRProvider()
    utterance = "do log ghayal hain"
    chunks = await collect(asr.stream_transcribe(text_audio_stream(utterance, asr_confidence=0.9)))

    # Exactly one final, and it is the last chunk.
    finals = [c for c in chunks if c.is_final]
    assert len(finals) == 1
    assert chunks[-1].is_final
    final = finals[0]
    assert final.text == utterance

    # At least one partial, all before the final, each a growing word-prefix.
    partials = [c for c in chunks if not c.is_final]
    assert len(partials) >= 1
    for p in partials:
        assert utterance.startswith(p.text)
        assert len(p.text) < len(final.text)


@pytest.mark.asyncio
async def test_confidence_in_range_and_partials_not_more_confident():
    asr = MockASRProvider()
    stream = text_audio_stream("accident ho gaya", asr_confidence=0.91)
    chunks = await collect(asr.stream_transcribe(stream))
    final = chunks[-1]
    for c in chunks:
        assert 0.0 <= c.confidence <= 1.0
        if not c.is_final:
            assert c.confidence <= final.confidence
    assert final.confidence == 0.91


@pytest.mark.asyncio
async def test_silence_yields_low_confidence_empty_final():
    asr = MockASRProvider()
    chunks = await collect(asr.stream_transcribe(text_audio_stream("", asr_confidence=0.2)))
    assert len(chunks) == 1
    assert chunks[0].is_final
    assert chunks[0].text == ""
    assert chunks[0].confidence <= 0.3


@pytest.mark.asyncio
async def test_confidence_derived_when_not_supplied():
    # No asr_confidence hint → heuristic. Laughter markers read as low quality.
    asr = MockASRProvider()
    chunks = await collect(asr.stream_transcribe(text_audio_stream("hahaha hello *laughing*")))
    assert chunks[-1].confidence < 0.7
