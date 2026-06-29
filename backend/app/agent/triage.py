"""TriageAgent — the brain (spec §3).

Given a conversation (caller turns, plus optional caller reputation) it produces
a correct *and safe* :class:`IncidentCard`, a severity, and a :class:`RouteDecision`
— with no dependency on telephony or audio. The pipeline is deliberately layered
so the safety-critical decision is never at the mercy of the (mock) LLM:

    turns ─▶ signals ─▶ severity classifier ─┐
                     └▶ junk scorer ─────────┤
              LLM extract (fields only) ─────┤
                                             ▼
                          reconcile → critical-keyword override
                                             ▼
                          confidence → safety floors → route

The LLM is asked only for the "what was said" fields; severity and confidence
come from the agent's own rules, and the safety layer has the final word.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.adapters.base import LLMProvider
from app.agent import extraction, safety
from app.agent.junk import JunkAssessment, score_junk
from app.agent.severity import SeverityVerdict, classify_severity
from app.agent.signals import (
    CallerContext,
    CallerTurn,
    ConversationSignals,
    build_signals,
)
from app.agent.state_machine import DialogueStep, TriageStateMachine
from app.domain.enums import CallState, RouteTarget, Severity
from app.domain.models import IncidentCard, RouteDecision

_ROUTE_TO_STATE: dict[RouteTarget, CallState] = {
    RouteTarget.OPERATOR_IMMEDIATE: CallState.ROUTED,
    RouteTarget.OPERATOR_QUEUE: CallState.ROUTED,
    RouteTarget.AI_RESOLVE: CallState.RESOLVED,
    RouteTarget.AUTO_RESOLVE: CallState.RESOLVED,
}


@dataclass(frozen=True)
class TriageOutcome:
    """Everything the agent decided about a call."""

    card: IncidentCard
    route: RouteDecision
    junk: JunkAssessment
    signals: ConversationSignals
    dialogue: tuple[DialogueStep, ...]
    final_state: CallState

    @property
    def severity(self) -> Severity:
        return self.card.severity


class TriageAgent:
    """Stateless triage brain over an :class:`LLMProvider`."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def _final_severity(
        self,
        signals: ConversationSignals,
        verdict: SeverityVerdict,
        junk: JunkAssessment,
    ) -> tuple[Severity, list[str]]:
        reasons = list(verdict.reasons)

        if junk.is_junk and not signals.has_emergency_kw:
            severity = Severity.JUNK
            reasons.append(f"junk p={junk.probability:.2f}: " + ", ".join(junk.reasons))
        else:
            severity = verdict.severity

        escalated = safety.critical_keyword_override(severity, signals)
        if escalated is not severity:
            reasons.append(
                f"critical-keyword override: {severity.value} → {escalated.value}"
            )
        return escalated, reasons

    async def triage(
        self,
        turns: Sequence[CallerTurn],
        *,
        caller: CallerContext | None = None,
    ) -> TriageOutcome:
        signals = build_signals(turns, caller=caller)
        junk = score_junk(signals)
        verdict = classify_severity(signals)
        severity, reasons = self._final_severity(signals, verdict, junk)
        confidence = safety.compute_confidence(signals, severity, junk)

        # LLM provides the "what was said" fields; the agent owns the decision.
        draft = await extraction.extract_card(self._llm, signals.text)

        card = IncidentCard(
            caller_name=extraction.extract_caller_name(turns) or draft.caller_name,
            location_text=extraction.extract_location(turns) or draft.location_text,
            incident_type=verdict.incident_type,
            people_involved=(
                signals.people_involved
                if signals.people_involved is not None
                else draft.people_involved
            ),
            severity=severity,
            confidence=confidence,
            needs_ambulance=verdict.needs_ambulance or draft.needs_ambulance,
            needs_police=verdict.needs_police or draft.needs_police,
            needs_fire=verdict.needs_fire or draft.needs_fire,
            summary=draft.summary or (signals.text[:280] or None),
            details={
                "severity_reasons": reasons,
                "junk_probability": junk.probability,
                "junk_signals": list(junk.reasons),
            },
        )

        route = safety.decide_route(card)
        dialogue = TriageStateMachine().drive(turns)
        final_state = _ROUTE_TO_STATE[route.target]

        return TriageOutcome(
            card=card,
            route=route,
            junk=junk,
            signals=signals,
            dialogue=tuple(dialogue),
            final_state=final_state,
        )
