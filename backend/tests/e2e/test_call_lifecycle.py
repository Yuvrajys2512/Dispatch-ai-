"""End-to-end call lifecycle — the Phase 4 verifiable output.

One simulated call is driven through the whole live pipeline (mock telephony →
ASR → agent → TTS), and we assert on the realtime event stream it produces:

* events arrive **ordered** (``call.started`` first, ``call.ended`` last, with a
  per-call contiguous ``seq``);
* the incident card fills **progressively** across ``incident.updated`` events;
* the call **routes correctly** (matching the Phase 3 corpus expectation);
* a **take-over** cleanly bridges a human, drops the AI, and lands ``HANDED_OVER``;
* a mid-call **hangup** lands ``ABANDONED``; and
* the simulator runs **1–5 concurrent** calls with no stuck "live" state.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.factory import (
    get_asr_provider,
    get_llm_provider,
    get_tts_provider,
)
from app.adapters.mock.scenarios import get_scenario
from app.adapters.mock.telephony import MockTelephonyProvider
from app.agent.triage import TriageAgent
from app.domain.enums import CallState, RouteTarget, Severity
from app.orchestrator.session import CallSession
from app.realtime.events import Event
from app.simulator.runner import _caller_context, simulate

# --- helpers --------------------------------------------------------------


async def _make_session(scenario_id, *, hub, store, session_factory, registry):
    """Build a CallSession for one scenario (one incoming mock call)."""
    scenario = get_scenario(scenario_id)
    telephony = MockTelephonyProvider([scenario])
    incoming = None
    async for inc in telephony.incoming_calls():
        incoming = inc
        break
    assert incoming is not None

    session = CallSession(
        incoming,
        telephony=telephony,
        asr=get_asr_provider(),
        tts=get_tts_provider(),
        agent=TriageAgent(get_llm_provider()),
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
        caller_context=_caller_context(scenario),
    )
    return session, telephony, incoming


async def _run_collecting(hub, session, *, trigger_on=None, action=None):
    """Run ``session`` while draining ``hub``; optionally fire ``action`` once
    the first event of type ``trigger_on`` is seen. Returns (call, events)."""
    events: list[Event] = []
    async with hub.subscribe() as queue:
        task = asyncio.create_task(session.run())
        fired = False
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.05)
            except TimeoutError:
                if task.done():
                    break
                continue
            events.append(event)
            if not fired and trigger_on and event.type == trigger_on:
                fired = True
                await action()
        call = await task
        while not queue.empty():
            events.append(queue.get_nowait())
    return call, events


def _types(events: list[Event]) -> list[str]:
    return [e.type for e in events]


# --- tests ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_ordering_and_progressive_card(
    hub, store, session_factory, registry
):
    session, _telephony, _incoming = await _make_session(
        "accident_injuries",
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
    )
    call, events = await _run_collecting(hub, session)
    types = _types(events)

    # Ordered + contiguous monotonic seq.
    assert types[0] == "call.started"
    assert types[-1] == "call.ended"
    assert [e.seq for e in events] == list(range(len(events)))

    # A partial precedes the first final (real streaming, not batch).
    assert "transcript.partial" in types
    assert types.index("transcript.partial") < types.index("transcript.final")

    # route.decided happens, and strictly before call.ended.
    assert types.index("route.decided") < types.index("call.ended")

    # Progressive card fill: >= 2 incident.updated, location arrives later.
    incident_events = [e for e in events if e.type == "incident.updated"]
    assert len(incident_events) >= 2
    assert incident_events[0].incident.location_text is None
    assert incident_events[-1].incident.location_text is not None

    # Correct triage: a road accident is CRITICAL → immediate human handoff.
    assert call.incident.severity is Severity.CRITICAL
    assert call.route is not None
    assert call.route.target is RouteTarget.OPERATOR_IMMEDIATE
    assert call.state is CallState.ROUTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario_id", "severity", "target"),
    [
        ("accident_injuries", Severity.CRITICAL, RouteTarget.OPERATOR_IMMEDIATE),
        ("chest_pain_only", Severity.HIGH, RouteTarget.OPERATOR_IMMEDIATE),
        ("theft_reported", Severity.MEDIUM, RouteTarget.OPERATOR_QUEUE),
        ("info_nearest_hospital", Severity.LOW, RouteTarget.AI_RESOLVE),
        ("prank_laughter", Severity.JUNK, RouteTarget.AUTO_RESOLVE),
        ("silent_accidental", Severity.JUNK, RouteTarget.AUTO_RESOLVE),
    ],
)
async def test_routes_match_corpus(
    hub, store, session_factory, registry, scenario_id, severity, target
):
    session, _telephony, _incoming = await _make_session(
        scenario_id,
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
    )
    call, events = await _run_collecting(hub, session)

    assert call.incident.severity is severity
    assert call.route is not None and call.route.target is target
    # The live route must equal the scenario's declared expectation.
    expected = get_scenario(scenario_id).expected
    assert expected is not None
    assert call.route.target.value == expected.route
    assert call.incident.severity.value == expected.severity


@pytest.mark.asyncio
async def test_severity_changes_emitted_on_escalation(
    hub, store, session_factory, registry
):
    # Silent first (looks like junk), then a faint cry → must escalate to HIGH.
    session, _telephony, _incoming = await _make_session(
        "silent_then_faint_cry",
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
    )
    call, events = await _run_collecting(hub, session)

    changes = [e for e in events if e.type == "severity.changed"]
    assert changes, "expected a severity.changed event on escalation"
    assert changes[-1].current is Severity.HIGH
    assert call.incident.severity is Severity.HIGH
    assert call.route.target is RouteTarget.OPERATOR_IMMEDIATE


@pytest.mark.asyncio
async def test_clean_takeover_drops_ai(hub, store, session_factory, registry):
    session, telephony, incoming = await _make_session(
        "accident_injuries",
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
    )

    async def _takeover():
        await session.take_over(reason="supervisor takeover")

    call, events = await _run_collecting(
        hub, session, trigger_on="transcript.final", action=_takeover
    )
    types = _types(events)

    # The take-over event fired, the human is bridged, the AI dropped out.
    assert "operator.takeover" in types
    assert incoming.call_id in telephony.bridged
    assert incoming.call_id not in telephony.hung_up  # human holds the line
    assert call.state is CallState.HANDED_OVER
    # A handed-over call is not AI-routed.
    assert "route.decided" not in types
    # Still ends cleanly, takeover before the end.
    assert types[-1] == "call.ended"
    assert types.index("operator.takeover") < types.index("call.ended")


@pytest.mark.asyncio
async def test_caller_hangup_is_abandoned(hub, store, session_factory, registry):
    session, telephony, incoming = await _make_session(
        "accident_injuries",
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
    )
    # Caller drops as soon as they connect → ABANDONED, no AI route.
    session.caller_hangup()
    call, events = await _run_collecting(hub, session)
    types = _types(events)

    assert call.state is CallState.ABANDONED
    assert incoming.call_id in telephony.hung_up
    assert "route.decided" not in types
    assert types[0] == "call.started"
    assert types[-1] == "call.ended"


@pytest.mark.asyncio
async def test_asr_failure_falls_back_to_human(hub, store, session_factory, registry):
    scenario = get_scenario("accident_injuries")
    telephony = MockTelephonyProvider([scenario])
    incoming = None
    async for inc in telephony.incoming_calls():
        incoming = inc
        break

    class _FailingASR:
        async def stream_transcribe(self, audio):
            async for _ in audio:  # consume one frame, then fail
                raise RuntimeError("ASR engine crashed")
                yield  # pragma: no cover

    session = CallSession(
        incoming,
        telephony=telephony,
        asr=_FailingASR(),
        tts=get_tts_provider(),
        agent=TriageAgent(get_llm_provider()),
        hub=hub,
        store=store,
        session_factory=session_factory,
        registry=registry,
        caller_context=_caller_context(scenario),
    )
    call, events = await _run_collecting(hub, session)
    types = _types(events)

    # ASR died → fall back to a human (handoff), call still terminates cleanly.
    assert call.state is CallState.ROUTED
    assert call.route is not None and call.route.handoff is True
    assert call.route.target is RouteTarget.OPERATOR_IMMEDIATE
    assert "route.decided" in types
    assert types[-1] == "call.ended"


@pytest.mark.asyncio
async def test_concurrent_simulation(hub, store, session_factory, registry):
    scenario_ids = ["accident_injuries", "theft_reported", "prank_laughter"]
    calls = await simulate(
        scenario_ids,
        concurrency=3,
        hub=hub,
        store=store,
        registry=registry,
        session_factory=session_factory,
    )

    assert len(calls) == 3
    assert all(c.state.is_terminal for c in calls)
    by_phone = {c.phone: c for c in calls}
    # Each scenario reached its expected route, run concurrently.
    for sid in scenario_ids:
        scenario = get_scenario(sid)
        call = by_phone[scenario.from_number]
        assert call.route is not None
        assert call.route.target.value == scenario.expected.route

    # No stuck "live" calls left in Redis after everyone terminated.
    assert await store.active_calls() == []


@pytest.mark.asyncio
async def test_concurrency_bounds_are_enforced(hub, store, session_factory, registry):
    from app.simulator.runner import CallSimulator

    for bad in (0, 6):
        with pytest.raises(ValueError):
            CallSimulator(
                hub=hub,
                store=store,
                registry=registry,
                session_factory=session_factory,
                concurrency=bad,
            )
