"""Per-call async session — the live streaming pipeline (spec §3, Phase 4).

A :class:`CallSession` owns one emergency call end-to-end: it wires the streaming
adapters (telephony → ASR → agent → TTS → telephony) into a single async task,
emits the ordered :mod:`~app.realtime.events` stream as the call unfolds, mirrors
the live :class:`~app.domain.models.Call` into Redis, and durably persists it via
the repositories. The brain itself (severity/junk/safety) is *not* reimplemented
here — every final transcript re-runs the stateless
:class:`~app.agent.triage.TriageAgent` over the growing turn list, so the card,
severity, and route fill in progressively while the safety guarantees from
Phase 3 hold unchanged.

Lifecycle (happy path)::

    start → greet → [for each caller utterance:
                        partial* → final → triage → incident/severity events
                        → speak the next question]
          → route.decided → call.ended

Plus three non-happy exits, all leaving a clean terminal state (Redis TTL means a
crashed session never leaks a stuck "live" call):

    * **take-over** — a human is bridged in; the AI drops out  → ``HANDED_OVER``
    * **caller hangup** mid-call                               → ``ABANDONED``
    * **ASR failure** — the pipeline raised; fall back to human → ``ROUTED`` (handoff)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import (
    ASRProvider,
    IncomingCall,
    TelephonyProvider,
    TranscriptChunk,
    TTSProvider,
)
from app.agent.prompts import prompt_for
from app.agent.signals import CallerContext, CallerTurn
from app.agent.triage import TriageAgent, TriageOutcome
from app.db.caller_counter import CallerCallCounter
from app.db.redis_store import CallStateStore
from app.db.repositories import CallerRepository, CallRepository
from app.db.session import session_scope
from app.domain.enums import CallState, RouteTarget, Speaker
from app.domain.models import Call, RouteDecision
from app.orchestrator.latency import LatencyTracker
from app.orchestrator.registry import SessionRegistry, default_registry
from app.realtime.events import (
    CallEnded,
    CallStarted,
    Event,
    IncidentUpdated,
    OperatorTakeover,
    RouteDecided,
    SeverityChanged,
    TranscriptFinal,
    TranscriptPartial,
)
from app.realtime.hub import EventHub, default_hub

logger = logging.getLogger("dispatch.session")

# An async-context-manager factory yielding a session (``session_scope`` shape).
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class CallSession:
    """Drives a single call through the streaming triage pipeline."""

    def __init__(
        self,
        incoming: IncomingCall,
        *,
        telephony: TelephonyProvider,
        asr: ASRProvider,
        tts: TTSProvider,
        agent: TriageAgent,
        hub: EventHub | None = None,
        store: CallStateStore,
        session_factory: SessionFactory = session_scope,
        registry: SessionRegistry | None = None,
        caller_context: CallerContext | None = None,
        caller_counter: CallerCallCounter | None = None,
    ) -> None:
        self._incoming = incoming
        self._tel = telephony
        self._asr = asr
        self._tts = tts
        self._agent = agent
        self._hub = hub or default_hub
        self._store = store
        self._session_factory = session_factory
        self._registry = registry or default_registry
        self._caller_context = caller_context
        # Phase 6: when a counter is supplied the live caller reputation
        # (today's call count + DB blacklist/flagged) is built at call start and
        # replaces any scripted ``caller_context``. Left None, behaviour is the
        # pre-Phase-6 scripted reputation (kept for focused unit tests).
        self._caller_counter = caller_counter

        # The telephony handle (e.g. "mock-accident_injuries") vs the durable
        # domain id. Events/registry/Redis all key on the domain id; only the
        # adapter calls use the telephony id.
        self._tel_call_id = incoming.call_id
        self._call = Call(phone=incoming.from_number)

        self._caller_turns: list[CallerTurn] = []
        self._latest_outcome: TriageOutcome | None = None
        self._prev_severity = None
        self._prev_card_snapshot: dict | None = None
        self._reply_idx = 1  # dialogue[0] is the greeting, already spoken
        self._seq = 0
        self._turn_mark = perf_counter()
        self._pending_events: list[Event] = []

        self._taken_over = False
        self._hangup_requested = False
        self._asr_failed = False
        self._ended = False
        self._pending_audit: list[tuple[str, dict]] = []

        self.tracker = LatencyTracker(call_id=str(self._call.id))

    # --- identity --------------------------------------------------------

    @property
    def call_id(self) -> str:
        """The durable, public call id (stringified domain UUID)."""
        return str(self._call.id)

    @property
    def call(self) -> Call:
        return self._call

    # --- external triggers ----------------------------------------------

    async def take_over(self, reason: str = "manual operator takeover") -> None:
        """Bridge a human into the live call; the AI drops out (→ HANDED_OVER)."""
        if self._ended or self._taken_over:
            return
        self._taken_over = True
        await self._tel.bridge_to_operator(self._tel_call_id)
        self._call.state = CallState.HANDED_OVER
        await self._emit(OperatorTakeover, reason=reason)
        await self._persist()

    def caller_hangup(self) -> None:
        """Signal that the caller hung up; the pipeline tears down → ABANDONED."""
        self._hangup_requested = True

    # --- the pipeline ----------------------------------------------------

    async def run(self) -> Call:
        """Run the whole call to a terminal state and return the final Call."""
        await self._start()
        try:
            await self._greet()
            await self._consume()
        except Exception:  # noqa: BLE001 - any pipeline fault → human fallback
            logger.exception("pipeline failure on call %s; routing to human", self.call_id)
            self._asr_failed = True
        await self._finalize()
        return self._call

    async def _start(self) -> None:
        self._registry.register(self)
        async with self._session_factory() as s:
            caller = await CallerRepository(s).get_or_create(self._call.phone)
            self._call.caller_id = caller.id
            await CallRepository(s).create(self._call)
        # Phase 6: build the *live* caller reputation the junk scorer reads —
        # today's rolling call count from Redis (this call counts now) plus the
        # blacklist/flagged-prank flags from the DB. This is what makes a repeat
        # caller flag on their 3rd call of the day and a blacklisted number fire
        # the strong junk weight, sourced from real data rather than a script.
        if self._caller_counter is not None:
            calls_today = await self._caller_counter.increment(self._call.phone)
            self._caller_context = CallerContext(
                calls_today=calls_today,
                is_blacklisted=caller.is_blacklisted,
                flagged_prank=caller.flagged_prank,
            )
        await self._store.set(self._call)
        await self._emit(
            CallStarted,
            phone=self._call.phone,
            scenario=self._incoming.metadata.get("scenario"),
        )

    async def _greet(self) -> None:
        if self._taken_over or self._hangup_requested:
            return
        line = prompt_for(CallState.GREETING)
        self._call.add_turn(Speaker.AI, line)
        await self._speak(line)
        self._turn_mark = perf_counter()

    async def _consume(self) -> None:
        audio = self._tel.caller_audio(self._tel_call_id)
        async for chunk in self._asr.stream_transcribe(audio):
            if self._taken_over or self._hangup_requested:
                break
            if not chunk.is_final:
                await self._emit(
                    TranscriptPartial, text=chunk.text, confidence=chunk.confidence
                )
                continue
            await self._handle_final(chunk)

    async def _handle_final(self, chunk: TranscriptChunk) -> None:
        self.tracker.record("asr", (perf_counter() - self._turn_mark) * 1000.0)

        turn = self._call.add_turn(
            Speaker.CALLER, chunk.text, confidence=chunk.confidence
        )
        await self._emit(
            TranscriptFinal,
            text=chunk.text,
            confidence=chunk.confidence,
            turn_seq=turn.seq,
        )

        self._caller_turns.append(
            CallerTurn(
                text=chunk.text,
                confidence=chunk.confidence,
                silent=not chunk.text.strip(),
            )
        )

        with self.tracker.measure("llm"):
            outcome = await self._agent.triage(
                self._caller_turns, caller=self._caller_context
            )
        self._latest_outcome = outcome
        await self._apply_outcome(outcome)
        await self._persist()

        if not self._taken_over:
            line = self._next_reply_line(outcome)
            self._call.add_turn(Speaker.AI, line)
            await self._speak(line)
        self._turn_mark = perf_counter()

    async def _apply_outcome(self, outcome: TriageOutcome) -> None:
        """Fold the triage result into the live card; emit diffs."""
        card = outcome.card
        self._call.incident = card

        snapshot = card.model_dump(mode="json")
        if snapshot != self._prev_card_snapshot:
            await self._emit(IncidentUpdated, incident=card)
            self._prev_card_snapshot = snapshot

        if self._prev_severity is not None and card.severity != self._prev_severity:
            await self._emit(
                SeverityChanged, previous=self._prev_severity, current=card.severity
            )
        self._prev_severity = card.severity

    def _next_reply_line(self, outcome: TriageOutcome) -> str:
        dialogue = outcome.dialogue
        idx = min(self._reply_idx, len(dialogue) - 1)
        self._reply_idx += 1
        return dialogue[idx].ai_line

    async def _speak(self, text: str) -> None:
        """TTS the line and stream the frames back to the caller."""
        with self.tracker.measure("tts"):
            async for audio in self._tts.stream_synthesize(text):
                if self._taken_over:  # human has the line — stop talking
                    break
                with self.tracker.measure("network"):
                    await self._tel.send_audio(self._tel_call_id, audio)

    # --- teardown --------------------------------------------------------

    async def _finalize(self) -> None:
        if self._ended:
            return
        self._ended = True

        if self._taken_over:
            final_state = CallState.HANDED_OVER  # already set; human holds the line
        elif self._hangup_requested:
            final_state = CallState.ABANDONED
            await self._tel.hangup(self._tel_call_id)
        elif self._asr_failed:
            final_state = await self._route_to_human("asr_failure: routing to human")
            await self._tel.hangup(self._tel_call_id)
        elif self._latest_outcome is not None:
            route = self._latest_outcome.route
            self._call.route = route
            await self._emit_route(route)
            final_state = self._latest_outcome.final_state
            self._maybe_audit_auto_resolution(route)
            await self._tel.hangup(self._tel_call_id)
        else:
            # Connected but never said anything triageable before dropping.
            final_state = CallState.ABANDONED
            await self._tel.hangup(self._tel_call_id)

        self._call.state = final_state
        self._call.ended_at = datetime.now(UTC)
        await self._emit(
            CallEnded,
            final_state=final_state,
            duration_seconds=self._call.duration_seconds,
        )
        await self._persist()
        self.tracker.log_table()
        self._registry.deregister(self.call_id)

    def _maybe_audit_auto_resolution(self, route: RouteDecision) -> None:
        """Record an explicit audit row when high-confidence junk auto-resolves.

        ``AUTO_RESOLVE`` is the one route that closes a call **without ever
        touching an operator**. We write a dedicated ``junk.auto_resolved`` event
        (probability + the junk signals that fired) on top of the generic event
        log so the "AI filtered this, no human involved" decision is auditable
        and reconcilable in analytics. The route itself already guarantees this
        path carries no handoff and no operator target.
        """
        if route.target is not RouteTarget.AUTO_RESOLVE:
            return
        junk = self._latest_outcome.junk if self._latest_outcome else None
        self._pending_audit.append(
            (
                "junk.auto_resolved",
                {
                    "probability": junk.probability if junk else None,
                    "reasons": list(junk.reasons) if junk else [],
                    "severity": route.severity.value,
                    "confidence": route.confidence,
                },
            )
        )

    async def _route_to_human(self, reason: str) -> CallState:
        card = self._call.incident
        route = RouteDecision(
            target=RouteTarget.OPERATOR_IMMEDIATE,
            severity=card.severity,
            confidence=card.confidence,
            reason=reason,
            handoff=True,
        )
        self._call.route = route
        await self._emit_route(route)
        return CallState.ROUTED

    async def _emit_route(self, route: RouteDecision) -> None:
        await self._emit(
            RouteDecided,
            target=route.target,
            severity=route.severity,
            confidence=route.confidence,
            reason=route.reason,
            handoff=route.handoff,
        )

    # --- plumbing --------------------------------------------------------

    async def _emit(self, event_cls: type, **fields) -> None:
        event = event_cls(call_id=self.call_id, seq=self._seq, **fields)
        self._seq += 1
        self._pending_events.append(event)
        await self._hub.publish(event)

    async def _persist(self) -> None:
        async with self._session_factory() as s:
            repo = CallRepository(s)
            await repo.update(self._call)
            while self._pending_events:
                event = self._pending_events.pop(0)
                await repo.log_event(
                    self._call.id, event.type, event.model_dump(mode="json")
                )
            while self._pending_audit:
                kind, payload = self._pending_audit.pop(0)
                await repo.log_event(self._call.id, kind, payload)
        await self._store.set(self._call)
