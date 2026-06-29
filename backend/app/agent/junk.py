"""Junk detection — weighted, behavioural, content-blind.

Implements the weighted-signal model from spec §"Junk Call Detection". Each
present signal contributes a weight; the weights combine via a noisy-OR so any
single strong signal pushes the probability high and several stack toward
certainty. This scorer looks *only* at behaviour (silence, laughter, abuse,
repeat/blacklist, wrong-number, incoherence) — never at emergency content. That
separation is deliberate: the severity classifier owns "is this an emergency",
the junk scorer owns "is this a time-waster", and the safety layer reconciles
them so a real emergency can never be silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.signals import ConversationSignals

# Signal → weight (spec §Junk Detection table: High ≈ 0.8–0.95, Medium ≈ 0.4).
_W_BLACKLIST = 0.95
_W_SILENCE = 0.9
_W_WRONG_NUMBER = 0.88
_W_LAUGHTER = 0.8
_W_LEWD = 0.8
_W_ABUSE = 0.8
_W_REPEAT = 0.75  # 3+ calls today
_W_TIMEPASS = 0.7
_W_FLAGGED_PRANK = 0.6
_W_VERY_SHORT = 0.45  # medium: short, contentless
_W_INCOHERENT = 0.4  # medium: nonsensical / no parseable content

# Above this probability we treat the call as junk (when it carries no emergency
# content). Below it the call is merely "noisy" and falls through to normal
# triage. 0.6 keeps a single medium signal from auto-resolving anything.
JUNK_THRESHOLD = 0.6


@dataclass(frozen=True)
class JunkAssessment:
    probability: float
    is_junk: bool
    reasons: tuple[str, ...]


def _noisy_or(weights: list[float]) -> float:
    """Combine independent signal weights: 1 - ∏(1 - w)."""
    prob = 1.0
    for w in weights:
        prob *= (1.0 - w)
    return 1.0 - prob


def score_junk(signals: ConversationSignals) -> JunkAssessment:
    """Probability the call is a time-waster, plus the signals that fired."""
    weights: list[float] = []
    reasons: list[str] = []

    def add(present: bool, weight: float, why: str) -> None:
        if present:
            weights.append(weight)
            reasons.append(why)

    c = signals.caller
    add(c.is_blacklisted, _W_BLACKLIST, "blacklisted number")
    add(c.calls_today >= 3, _W_REPEAT, f"repeat caller ({c.calls_today} today)")
    add(c.flagged_prank, _W_FLAGGED_PRANK, "flagged as prank")
    add(signals.has_silence, _W_SILENCE, "silence after greeting")
    add(signals.has_wrong_number, _W_WRONG_NUMBER, "wrong number")
    add(signals.has_laughter, _W_LAUGHTER, "laughter / party noise")
    add(signals.has_lewd, _W_LEWD, "lewd content")
    add(signals.has_abuse, _W_ABUSE, "abusive content")
    add(signals.has_timepass, _W_TIMEPASS, "timepass / testing")
    # Contentless-short and incoherence only count when nothing emergency-y is
    # present (avoids penalising a panicked, broken-Hindi real caller).
    if not signals.has_emergency_kw and not signals.has_override_cry:
        add(signals.is_very_short, _W_VERY_SHORT, "very short, no content")
        add(signals.is_incoherent, _W_INCOHERENT, "incoherent / nonsensical")

    probability = round(_noisy_or(weights), 4)
    is_junk = probability >= JUNK_THRESHOLD
    return JunkAssessment(
        probability=probability,
        is_junk=is_junk,
        reasons=tuple(reasons),
    )
