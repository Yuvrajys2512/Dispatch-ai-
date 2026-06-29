"""Safety layer — the hard, hard-coded, test-gated rules (spec §4 + §Junk).

Three non-negotiable rules live here, and only here, so they cannot be diluted
by anything upstream:

1. **Critical-keyword override.** If a call carries a critical cry/keyword
   (help, accident, blood, fire, bachao, madad, …) it can never end up below
   HIGH — even if the junk scorer was certain it was a prank. "A scared person
   might sound incoherent — that's not a prank." This is what guarantees *zero
   false negatives*.

2. **Confidence floor.** AI confidence below
   :data:`~app.domain.models.CONFIDENCE_HANDOFF_THRESHOLD` (0.80) ⇒ hand off to
   a human. The AI must never be the reason a real emergency is delayed.

3. **Severity floor.** ``severity ≥ HIGH`` ⇒ instant handoff.

Rules 2 and 3 are exactly :attr:`IncidentCard.requires_handoff`; this module is
where they are *enforced* and turned into a concrete route.
"""

from __future__ import annotations

from app.agent.junk import JunkAssessment
from app.agent.signals import ConversationSignals
from app.domain.enums import RouteTarget, Severity
from app.domain.models import (
    CONFIDENCE_HANDOFF_THRESHOLD,
    IncidentCard,
    RouteDecision,
)

# How strongly a (non-junk) classification is "trusted" before blending with the
# ASR understanding confidence. Clear life-threat language is more trustworthy
# than a vague info request.
_SIGNAL_STRENGTH: dict[Severity, float] = {
    Severity.CRITICAL: 0.92,
    Severity.HIGH: 0.88,
    Severity.MEDIUM: 0.82,
    Severity.LOW: 0.78,
    Severity.JUNK: 0.5,
}


def critical_keyword_override(
    severity: Severity, signals: ConversationSignals
) -> Severity:
    """Re-escalate anything below HIGH that contains a critical cry/keyword.

    Never lowers severity. A concrete life-threat word → CRITICAL; a bare cry
    for help → HIGH. This is the spec's false-positive safeguard and the reason
    a junk-looking real emergency is always caught.
    """
    if severity >= Severity.HIGH:
        return severity
    if signals.has_override_critical or signals.has_critical_kw:
        return Severity.CRITICAL
    if signals.has_override_cry:
        return Severity.HIGH
    return severity


def compute_confidence(
    signals: ConversationSignals,
    severity: Severity,
    junk: JunkAssessment,
) -> float:
    """AI's confidence in *acting on this triage autonomously*, 0–1.

    For junk it is the certainty the call really is junk (junk probability) — so
    only confidently-junk calls auto-resolve and a borderline one is handed off.
    For everything else it blends how trustworthy the class is with how clearly
    we understood the caller (ASR), with a penalty for incoherent/code-switched
    speech.
    """
    if severity is Severity.JUNK:
        return round(min(junk.probability, 0.99), 2)

    understanding = signals.avg_confidence
    if signals.is_incoherent:
        understanding -= 0.10
    if signals.has_silence:
        understanding -= 0.10
    understanding = max(0.0, min(understanding, 1.0))

    strength = _SIGNAL_STRENGTH[severity]
    blended = 0.6 * strength + 0.4 * understanding
    return round(max(0.0, min(blended, 1.0)), 2)


def requires_handoff(severity: Severity, confidence: float) -> bool:
    """The authoritative safety predicate (mirrors IncidentCard.requires_handoff)."""
    return severity >= Severity.HIGH or confidence < CONFIDENCE_HANDOFF_THRESHOLD


def decide_route(card: IncidentCard, *, reason: str = "") -> RouteDecision:
    """Turn a triaged card into a terminal route, enforcing the safety floors."""
    handoff = card.requires_handoff

    if card.severity is Severity.JUNK and not handoff:
        target = RouteTarget.AUTO_RESOLVE
    elif handoff:
        target = RouteTarget.OPERATOR_IMMEDIATE
    elif card.severity is Severity.MEDIUM:
        target = RouteTarget.OPERATOR_QUEUE
    elif card.severity is Severity.LOW:
        target = RouteTarget.AI_RESOLVE
    else:
        # Defensive default: anything we can't confidently auto-handle goes to a
        # human, never to AUTO_RESOLVE.
        target = RouteTarget.OPERATOR_QUEUE

    return RouteDecision(
        target=target,
        severity=card.severity,
        confidence=card.confidence,
        handoff=handoff,
        reason=reason or "; ".join(filter(None, [_default_reason(card, target)])),
    )


def _default_reason(card: IncidentCard, target: RouteTarget) -> str:
    if target is RouteTarget.OPERATOR_IMMEDIATE:
        if card.severity >= Severity.HIGH:
            return f"{card.severity.value}: instant handoff (severity ≥ HIGH)"
        return f"confidence {card.confidence:.2f} < 0.80: instant handoff"
    if target is RouteTarget.AUTO_RESOLVE:
        return f"junk (confidence {card.confidence:.2f}): auto-resolved"
    if target is RouteTarget.OPERATOR_QUEUE:
        return f"{card.severity.value}: queued with pre-filled card"
    return f"{card.severity.value}: AI may resolve"
