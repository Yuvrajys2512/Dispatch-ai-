"""End-to-end: a real-mode inbound call runs the unchanged CallSession.

Drives the Exotel intake path with a fake media socket + recording Exotel client,
real Sarvam ASR/TTS adapters (fake transports), and the real Anthropic LLM adapter
(fake transport) — no telephony, no Sarvam/LLM accounts. Proves the real call
source feeds the *same* orchestrator, events, persistence, and routing as the
simulator: the AI answers, the agent triages, and a critical call routes to a human.
"""

from __future__ import annotations

import pytest

from app.adapters.exotel.intake import ExotelIntake
from app.adapters.exotel.telephony import ExotelTelephonyProvider
from app.agent.triage import TriageAgent
from app.db.caller_counter import CallerCallCounter
from app.domain.enums import CallState, RouteTarget, Severity
from tests.adapters.realfakes import (
    FakeMediaSocket,
    incoming,
    make_anthropic_provider,
    make_sarvam_asr_provider,
    make_sarvam_tts_provider,
    text_frames,
)


def _build_intake(
    store, session_factory, hub, registry
) -> tuple[ExotelIntake, ExotelTelephonyProvider]:
    from tests.adapters.realfakes import make_exotel_provider

    provider, _client = make_exotel_provider()
    intake = ExotelIntake(
        telephony=provider,
        asr=make_sarvam_asr_provider(),
        tts=make_sarvam_tts_provider(),
        agent=TriageAgent(make_anthropic_provider()),
        hub=hub,
        store=store,
        registry=registry,
        session_factory=session_factory,
        counter=CallerCallCounter(store.client),
    )
    return intake, provider


@pytest.mark.asyncio
async def test_real_inbound_critical_call_routes_to_human(
    store, session_factory, hub, registry
):
    intake, provider = _build_intake(store, session_factory, hub, registry)
    inc = incoming(call_id="exo-critical")
    transcript = "accident ho gaya do log ghayal hain khoon nikal raha hai"
    provider.offer_call(inc, FakeMediaSocket(text_frames(transcript)))
    provider.close()

    events: list[str] = []
    async with hub.subscribe() as queue:
        results = []
        async for incoming_call in provider.incoming_calls():
            results.append(await intake.handle_call(incoming_call))
        while not queue.empty():
            events.append(queue.get_nowait().type)

    call = results[0]
    # Same routing the simulator/dashboard would see — severity owned by the agent.
    assert call.incident.severity is Severity.CRITICAL
    assert call.route is not None and call.route.handoff is True
    assert call.route.target is RouteTarget.OPERATOR_IMMEDIATE
    assert call.state in (CallState.ROUTED, CallState.HANDED_OVER)
    # The real telephony hub recorded, spoke to the caller, and hung up.
    assert inc.call_id in provider.recorded
    assert provider.sent_audio[inc.call_id]  # the AI spoke (TTS frames sent)
    assert inc.call_id in provider.hung_up
    # The dashboard event stream fired for this call.
    assert "call.started" in events
    assert "route.decided" in events
    assert "call.ended" in events


@pytest.mark.asyncio
async def test_real_inbound_theft_is_not_dropped(
    store, session_factory, hub, registry
):
    intake, provider = _build_intake(store, session_factory, hub, registry)
    inc = incoming(call_id="exo-theft", from_number="+919800000001")
    provider.offer_call(inc, FakeMediaSocket(text_frames("mera phone chori ho gaya")))
    provider.close()

    results = []
    async for incoming_call in provider.incoming_calls():
        results.append(await intake.handle_call(incoming_call))

    call = results[0]
    assert call.incident.severity is Severity.MEDIUM
    assert inc.call_id in provider.hung_up
