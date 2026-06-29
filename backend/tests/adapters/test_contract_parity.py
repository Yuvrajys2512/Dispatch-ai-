"""Contract-parity gate — the *same* universal contract over mock + real.

The per-provider files (``test_contract_{telephony,asr,tts}.py``) cover each mock's
own behaviour; this file runs the **cross-provider contract** — the properties every
telephony/ASR/TTS provider must honour — over both the mock and the real adapter
(real driven by an in-memory fake transport from :mod:`tests.adapters.realfakes`).
No assertion is relaxed for the real adapter: it meets the identical bar.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.adapters.base import ASRProvider, TelephonyProvider, TTSProvider
from app.adapters.mock.asr import MockASRProvider
from app.adapters.mock.scenarios import THEFT
from app.adapters.mock.telephony import MockTelephonyProvider
from app.adapters.mock.tts import MockTTSProvider
from tests.adapters.helpers import collect, text_audio_stream
from tests.adapters.realfakes import (
    FakeMediaSocket,
    incoming,
    make_sarvam_asr_provider,
    make_sarvam_tts_provider,
    text_frames,
)

UTTERANCE = "do log ghayal hain"


# --- Telephony -----------------------------------------------------------

@pytest_asyncio.fixture(params=["mock", "real"])
async def telephony_case(request):
    if request.param == "mock":
        tel = MockTelephonyProvider([THEFT])
        calls = await collect(tel.incoming_calls())
        return tel, calls[0].call_id
    from tests.adapters.realfakes import make_exotel_provider

    tel, _client = make_exotel_provider()
    inc = incoming()
    tel.offer_call(inc, FakeMediaSocket(text_frames(UTTERANCE)))
    tel.close()
    calls = await collect(tel.incoming_calls())
    return tel, calls[0].call_id


def test_telephony_satisfies_protocol(telephony_case):
    tel, _ = telephony_case
    assert isinstance(tel, TelephonyProvider)


@pytest.mark.asyncio
async def test_caller_audio_streams_with_increasing_time_and_a_last_frame(telephony_case):
    tel, call_id = telephony_case
    frames = await collect(tel.caller_audio(call_id))
    assert frames, "expected inbound audio frames"
    assert sum(1 for f in frames if f.is_last) >= 1
    times = [f.t_ms for f in frames]
    assert times == sorted(times) and times[0] > 0


@pytest.mark.asyncio
async def test_send_bridge_hangup_observable(telephony_case):
    from app.adapters.base import AudioChunk

    tel, call_id = telephony_case
    await tel.send_audio(call_id, AudioChunk.from_text("madad aa rahi hai"))
    await tel.bridge_to_operator(call_id)
    await tel.hangup(call_id)
    assert len(tel.sent_audio[call_id]) == 1
    assert call_id in tel.bridged
    assert call_id in tel.hung_up


# --- ASR -----------------------------------------------------------------

@pytest.fixture(params=["mock", "real"])
def asr(request) -> ASRProvider:
    return MockASRProvider() if request.param == "mock" else make_sarvam_asr_provider()


def test_asr_satisfies_protocol(asr):
    assert isinstance(asr, ASRProvider)


@pytest.mark.asyncio
async def test_asr_partials_precede_final_and_are_prefixes(asr):
    chunks = await collect(
        asr.stream_transcribe(text_audio_stream(UTTERANCE, asr_confidence=0.9))
    )
    finals = [c for c in chunks if c.is_final]
    assert len(finals) == 1 and chunks[-1].is_final
    final = finals[0]
    assert final.text == UTTERANCE
    partials = [c for c in chunks if not c.is_final]
    assert len(partials) >= 1
    for p in partials:
        assert UTTERANCE.startswith(p.text)
        assert len(p.text) < len(final.text)


@pytest.mark.asyncio
async def test_asr_confidence_in_range_and_partials_not_more_confident(asr):
    chunks = await collect(
        asr.stream_transcribe(text_audio_stream(UTTERANCE, asr_confidence=0.9))
    )
    final = chunks[-1]
    for c in chunks:
        assert 0.0 <= c.confidence <= 1.0
        if not c.is_final:
            assert c.confidence <= final.confidence


@pytest.mark.asyncio
async def test_asr_silence_yields_low_confidence_empty_final(asr):
    chunks = await collect(asr.stream_transcribe(text_audio_stream("", asr_confidence=0.2)))
    assert len(chunks) == 1
    assert chunks[0].is_final
    assert chunks[0].text == ""
    assert chunks[0].confidence <= 0.3


# --- TTS -----------------------------------------------------------------

@pytest.fixture(params=["mock", "real"])
def tts(request) -> TTSProvider:
    return MockTTSProvider() if request.param == "mock" else make_sarvam_tts_provider()


def test_tts_satisfies_protocol(tts):
    assert isinstance(tts, TTSProvider)


@pytest.mark.asyncio
async def test_tts_streams_frames_with_fast_first_byte_and_one_last(tts):
    frames = await collect(tts.stream_synthesize("Aap line pe baney rahiye"))
    assert frames, "expected synthesized audio frames"
    assert frames[-1].is_last
    assert sum(1 for f in frames if f.is_last) == 1
    times = [f.t_ms for f in frames]
    assert times == sorted(times) and times[0] > 0


@pytest.mark.asyncio
async def test_tts_empty_text_yields_no_frames(tts):
    assert await collect(tts.stream_synthesize("   ")) == []
