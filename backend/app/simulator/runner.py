"""Call simulator — drive synthetic calls through the live pipeline.

The simulator is how we exercise the whole Phase 4 stack with **zero real
infrastructure**: it picks scripted :class:`~app.adapters.mock.scenarios.Scenario`
calls, hands each to a :class:`~app.orchestrator.session.CallSession`, and runs up
to ``concurrency`` of them at once (1–5). Everything downstream is real — the same
adapters, agent, events, persistence, and Redis mirror a production call uses —
only the *source* of the calls is scripted.

As of Phase 6 the live pipeline sources caller reputation from the **stores**, not
the script: at call start the session increments a per-day Redis counter and
reads the DB blacklist/flagged-prank flags into the
:class:`~app.agent.signals.CallerContext`. The scenario's scripted reputation is
kept only as a **seed** — before a batch runs, the simulator writes each
scenario's declared flags into the DB and pre-loads the Redis counter, so a
scripted "blacklisted" or "called 4 times today" caller is reproduced *through*
the real stores (and the corpus/e2e expectations still hold).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.factory import (
    get_asr_provider,
    get_llm_provider,
    get_tts_provider,
)
from app.adapters.mock.scenarios import (
    DEFAULT_SCENARIO_IDS,
    Scenario,
    get_scenario,
)
from app.adapters.mock.telephony import MockTelephonyProvider
from app.agent.signals import CallerContext
from app.agent.triage import TriageAgent
from app.db.caller_counter import CallerCallCounter
from app.db.redis_store import CallStateStore, get_redis
from app.db.repositories import CallerRepository
from app.db.session import session_scope
from app.domain.models import Call
from app.orchestrator.registry import SessionRegistry, default_registry
from app.orchestrator.session import CallSession, SessionFactory
from app.realtime.hub import EventHub, default_hub

logger = logging.getLogger("dispatch.simulator")

MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 5


def _caller_context(scenario: Scenario) -> CallerContext:
    return CallerContext(
        calls_today=scenario.caller_calls_today,
        is_blacklisted=scenario.caller_blacklisted,
        flagged_prank=scenario.caller_flagged_prank,
    )


class CallSimulator:
    """Launches scripted calls on demand or on a schedule (bounded concurrency)."""

    def __init__(
        self,
        *,
        hub: EventHub | None = None,
        store: CallStateStore | None = None,
        registry: SessionRegistry | None = None,
        session_factory: SessionFactory = session_scope,
        counter: CallerCallCounter | None = None,
        concurrency: int = 3,
    ) -> None:
        if not MIN_CONCURRENCY <= concurrency <= MAX_CONCURRENCY:
            raise ValueError(
                f"concurrency must be {MIN_CONCURRENCY}-{MAX_CONCURRENCY}, got {concurrency}"
            )
        self._hub = hub or default_hub
        self._store = store or CallStateStore(get_redis())
        self._registry = registry or default_registry
        self._session_factory = session_factory
        # The live repeat-caller counter shares the state store's Redis client by
        # default, so tests that inject a fakeredis-backed store get a matching
        # fakeredis counter for free (no extra wiring).
        self._counter = counter or CallerCallCounter(self._store.client)
        self._semaphore = asyncio.Semaphore(concurrency)

        # ASR/TTS/LLM are stateless across calls, so a single instance is shared;
        # telephony is shared too (it records per-call side effects by call id).
        self._asr = get_asr_provider()
        self._tts = get_tts_provider()
        self._agent = TriageAgent(get_llm_provider())

    async def run_scenarios(self, scenario_ids: Sequence[str]) -> list[Call]:
        """Run the named scenarios concurrently; return each final Call."""
        scenarios = [get_scenario(sid) for sid in scenario_ids]
        telephony = MockTelephonyProvider(scenarios)

        # Seed each scenario's scripted reputation into the live stores so the
        # session's live lookup reproduces it (DB flags + Redis counter floor).
        for scenario in scenarios:
            await self._seed_reputation(scenario)

        # Build a session per incoming call, then run them under the semaphore.
        sessions: list[CallSession] = []
        by_call: dict[str, Scenario] = {s.id: s for s in scenarios}
        async for incoming in telephony.incoming_calls():
            scenario = by_call[incoming.metadata["scenario"]]
            sessions.append(
                CallSession(
                    incoming,
                    telephony=telephony,
                    asr=self._asr,
                    tts=self._tts,
                    agent=self._agent,
                    hub=self._hub,
                    store=self._store,
                    session_factory=self._session_factory,
                    registry=self._registry,
                    caller_context=_caller_context(scenario),
                    caller_counter=self._counter,
                )
            )

        results = await asyncio.gather(*(self._run_one(s) for s in sessions))
        return list(results)

    async def _seed_reputation(self, scenario: Scenario) -> None:
        """Replay a scenario's scripted reputation through the live stores.

        Blacklist / flagged-prank flags go to the DB; a declared
        ``caller_calls_today`` pre-loads the Redis counter to one below the
        target so the call's own increment at start lands exactly on it. A
        scenario with no prior calls is left alone, so under ``--schedule`` an
        ordinary caller's count climbs naturally batch-over-batch and trips the
        repeat-caller weight on its real 3rd call of the day.
        """
        if scenario.caller_blacklisted or scenario.caller_flagged_prank:
            async with self._session_factory() as s:
                await CallerRepository(s).set_reputation(
                    scenario.from_number,
                    is_blacklisted=scenario.caller_blacklisted,
                    flagged_prank=scenario.caller_flagged_prank,
                )
        if scenario.caller_calls_today > 0:
            await self._counter.seed(
                scenario.from_number, scenario.caller_calls_today - 1
            )

    async def _run_one(self, session: CallSession) -> Call:
        async with self._semaphore:
            logger.info("simulating call %s", session.call_id)
            return await session.run()


async def simulate(
    scenario_ids: Sequence[str] | None = None,
    *,
    concurrency: int = 3,
    hub: EventHub | None = None,
    store: CallStateStore | None = None,
    registry: SessionRegistry | None = None,
    counter: CallerCallCounter | None = None,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]] = session_scope,
) -> list[Call]:
    """One-shot helper: run a batch of scenarios and return the final Calls."""
    simulator = CallSimulator(
        hub=hub,
        store=store,
        registry=registry,
        session_factory=session_factory,
        counter=counter,
        concurrency=concurrency,
    )
    return await simulator.run_scenarios(scenario_ids or DEFAULT_SCENARIO_IDS)
