"""Phase 6 live behaviour — caller history + junk auto-resolution, end to end.

These drive whole calls through the **live** pipeline (mock telephony → ASR →
agent → TTS) with the Phase 6 stores wired in, and assert on the real outcome:

* a repeat caller is flagged JUNK on their **3rd call of the day** (the Redis
  counter, not a script, makes the junk weight fire);
* high-confidence junk **auto-resolves** and writes a ``junk.auto_resolved``
  audit row, and **never** reaches an operator; and
* the **false-positive safeguard holds with live data** — a flagged-prank caller
  who reports a real accident is NOT junk and NOT auto-resolved.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.adapters.factory import get_asr_provider, get_llm_provider, get_tts_provider
from app.adapters.mock.scenarios import Scenario, ScriptedTurn, get_scenario
from app.adapters.mock.telephony import MockTelephonyProvider
from app.agent.triage import TriageAgent
from app.db.caller_counter import CallerCallCounter
from app.db.models import EventORM
from app.domain.enums import RouteTarget, Severity
from app.orchestrator.session import CallSession
from app.simulator.runner import simulate


async def _run_scenario(scenario, *, store, session_factory, registry, counter):
    """Drive one Scenario through a live CallSession; return the final Call."""
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
        store=store,
        session_factory=session_factory,
        registry=registry,
        caller_counter=counter,
    )
    return await session.run()


async def _events_of(engine: AsyncEngine, call_id, kind: str) -> list[EventORM]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        rows = await s.scalars(
            select(EventORM).where(
                EventORM.call_id == call_id, EventORM.kind == kind
            )
        )
        return list(rows)


@pytest.mark.asyncio
async def test_repeat_caller_flagged_on_third_call(
    store, session_factory, registry, engine
):
    """A neutral caller becomes JUNK on the 3rd call of the day via the counter."""
    counter = CallerCallCounter(store.client)
    # Content carries no emergency words and no other junk signal — only the
    # live repeat-caller count can tip this into JUNK.
    scenario = Scenario(
        id="neutral_repeat",
        from_number="+91-63000-99999",
        turns=(ScriptedTurn("haan ji kuch baat karni thi aapse", 0.9),),
    )

    severities: list[Severity] = []
    for _ in range(3):
        call = await _run_scenario(
            scenario,
            store=store,
            session_factory=session_factory,
            registry=registry,
            counter=counter,
        )
        severities.append(call.incident.severity)

    # Calls 1 and 2 are not junk; the 3rd call (calls_today == 3) trips it.
    assert severities[0] is not Severity.JUNK
    assert severities[1] is not Severity.JUNK
    assert severities[2] is Severity.JUNK
    assert await counter.get(scenario.from_number) == 3


@pytest.mark.asyncio
async def test_junk_auto_resolves_with_audit_and_no_operator(
    store, session_factory, registry, engine
):
    """High-confidence junk auto-resolves, writes an audit row, sees no operator."""
    scenario = get_scenario("prank_laughter")
    counter = CallerCallCounter(store.client)
    call = await _run_scenario(
        scenario,
        store=store,
        session_factory=session_factory,
        registry=registry,
        counter=counter,
    )

    assert call.incident.severity is Severity.JUNK
    assert call.route is not None
    assert call.route.target is RouteTarget.AUTO_RESOLVE
    assert call.route.handoff is False

    # The dedicated audit row exists and carries the junk diagnostics.
    audits = await _events_of(engine, call.id, "junk.auto_resolved")
    assert len(audits) == 1
    assert audits[0].payload["probability"] >= 0.6
    assert audits[0].payload["reasons"]

    # It never reached an operator: no operator.takeover audit, no operator route.
    takeovers = await _events_of(engine, call.id, "operator.takeover")
    assert takeovers == []
    assert call.route.target not in {
        RouteTarget.OPERATOR_IMMEDIATE,
        RouteTarget.OPERATOR_QUEUE,
    }


@pytest.mark.asyncio
async def test_flagged_caller_real_emergency_reescalates_live(
    store, session_factory, registry, engine
):
    """The false-positive safeguard holds on live data: flagged prank + real
    accident must NOT be junk and must NOT auto-resolve."""
    counter = CallerCallCounter(store.client)
    [call] = await simulate(
        ["repeat_caller_real_accident"],
        store=store,
        session_factory=session_factory,
        registry=registry,
        counter=counter,
        concurrency=1,
    )

    assert call.incident.severity is Severity.CRITICAL
    assert call.route is not None
    assert call.route.target is RouteTarget.OPERATOR_IMMEDIATE
    assert call.route.handoff is True
    # No auto-resolution audit was written for a real emergency.
    audits = await _events_of(engine, call.id, "junk.auto_resolved")
    assert audits == []
