"""Telephony contract: incoming-call stream, inbound audio, send/bridge/hangup."""

import pytest

from app.adapters.base import AudioChunk, IncomingCall, TelephonyProvider
from app.adapters.mock.scenarios import ACCIDENT, THEFT
from app.adapters.mock.telephony import MockTelephonyProvider
from tests.adapters.helpers import collect


def test_mock_satisfies_protocol():
    assert isinstance(MockTelephonyProvider(), TelephonyProvider)


@pytest.mark.asyncio
async def test_incoming_calls_emits_one_per_scenario_in_order():
    tel = MockTelephonyProvider([ACCIDENT, THEFT])
    calls = await collect(tel.incoming_calls())
    assert [c.from_number for c in calls] == [ACCIDENT.from_number, THEFT.from_number]
    assert all(isinstance(c, IncomingCall) for c in calls)
    assert calls[0].metadata["scenario"] == ACCIDENT.id


@pytest.mark.asyncio
async def test_caller_audio_replays_turn_and_marks_last_frame():
    tel = MockTelephonyProvider([THEFT])
    calls = await collect(tel.incoming_calls())
    call_id = calls[0].call_id

    frames = await collect(tel.caller_audio(call_id))
    assert frames, "expected inbound audio frames"
    # Exactly the turns that end an utterance carry is_last.
    assert sum(1 for f in frames if f.is_last) == len(THEFT.turns)
    # t_ms strictly increases (latency simulation).
    times = [f.t_ms for f in frames]
    assert times == sorted(times) and times[0] > 0
    # First utterance reconstructs from its frames.
    first_words = [f.text for f in frames if f.text][: len(THEFT.turns[0].text.split())]
    assert " ".join(first_words) == THEFT.turns[0].text


@pytest.mark.asyncio
async def test_send_audio_bridge_and_hangup_are_observable():
    tel = MockTelephonyProvider([ACCIDENT])
    calls = await collect(tel.incoming_calls())
    call_id = calls[0].call_id

    await tel.send_audio(call_id, AudioChunk.from_text("madad aa rahi hai"))
    await tel.bridge_to_operator(call_id)
    await tel.hangup(call_id)

    assert len(tel.sent_audio[call_id]) == 1
    assert call_id in tel.bridged
    assert call_id in tel.hung_up
