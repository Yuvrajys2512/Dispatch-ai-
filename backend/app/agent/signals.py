"""Conversation signals — the deterministic feature set the classifiers read.

The agent never lets a raw transcript reach the severity/junk logic directly.
Instead it distils the conversation (plus any caller reputation) into a flat,
inspectable :class:`ConversationSignals` bundle: which keyword families fired,
how clear the speech was (ASR confidence), whether the caller went silent, how
many people were mentioned, and so on. Classifiers are then pure functions of
this bundle — which is exactly what makes them unit-testable and the routing
decisions reproducible.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.agent import keywords as kw

_HINDI_NUMS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4,
    "paanch": 5, "panch": 5, "chhe": 6, "saat": 7, "aath": 8,
}
# Phrases that hint at several casualties even without a digit.
_MULTI_CASUALTY_RE = re.compile(
    r"\b(kai|kayi|many|multiple|several|bahut saare|do log|teen log|char log)\b",
    re.IGNORECASE,
)
_CHILD_RE = re.compile(
    r"\b(bachcha|baccha|bachche|bachchi|child|kid|baby|beta|beti|ladki choti)\b",
    re.IGNORECASE,
)
_DISTRESS_RE = re.compile(
    r"\b(scream|screaming|chilla|cheekh|ro raha|ro rahi|rote|crying|panic|"
    r"ghabra|sehmi|please please)\b",
    re.IGNORECASE,
)
# Code-switch / incoherence markers: trailing dots, "uh/um", mid-English in Hindi.
_INCOHERENCE_RE = re.compile(r"(\.\.\.|\buh\b|\bum\b|\berr\b|\bmatlab\b)", re.IGNORECASE)


@dataclass(frozen=True)
class CallerTurn:
    """One caller utterance handed to the agent (telephony/ASR-agnostic)."""

    text: str
    confidence: float = 0.9
    silent: bool = False


@dataclass(frozen=True)
class CallerContext:
    """Caller reputation the junk scorer may weigh (from Redis/DB in Phase 6)."""

    calls_today: int = 0
    is_blacklisted: bool = False
    flagged_prank: bool = False


@dataclass(frozen=True)
class ConversationSignals:
    """Everything the classifiers are allowed to look at — and nothing else."""

    text: str
    turn_count: int
    avg_confidence: float
    min_confidence: float
    # keyword families
    has_critical_kw: bool
    has_high_kw: bool
    has_theft_kw: bool
    has_domestic_kw: bool
    has_property_kw: bool
    has_info_kw: bool
    # behavioural / junk
    has_silence: bool
    has_laughter: bool
    has_timepass: bool
    has_wrong_number: bool
    has_lewd: bool
    has_abuse: bool
    is_incoherent: bool
    is_very_short: bool
    # safety override
    has_override_cry: bool
    has_override_critical: bool
    # extracted scalars
    people_involved: int | None
    multi_casualty: bool
    child_involved: bool
    distress: bool
    # caller reputation
    caller: CallerContext = field(default_factory=CallerContext)

    @property
    def has_emergency_kw(self) -> bool:
        """Any recognised incident content (NOT bare cries like 'help'/'bachao').

        Used to gate junk: a call that names a real incident — life-threat,
        medical/violence, theft, dispute, property, or an info request — can
        never be scored as junk. Bare cries are deliberately excluded here so the
        critical-keyword *override* still has work to do (and is exercised by a
        laughter-masked "bachao" call).
        """
        return (
            self.has_critical_kw
            or self.has_high_kw
            or self.has_theft_kw
            or self.has_domestic_kw
            or self.has_property_kw
            or self.has_info_kw
        )


# A "people" noun must sit near a number for it to count as a headcount — this
# stops road names ("NH-24") and sectors ("Sector 62") from being read as people.
_PEOPLE_NOUN = (
    r"(?:log|logon|logo|aadmi|aadmiyon|vyakti|bande|people|persons?|"
    r"injured|ghayal|zakhmi|casualt|mareez|bachch)"
)


def _people_involved(text: str) -> int | None:
    # digit + (a people noun within a short window)
    for m in re.finditer(r"\b(\d{1,3})\b", text):
        window = text[m.end() : m.end() + 16]
        if re.search(_PEOPLE_NOUN, window, re.IGNORECASE):
            return int(m.group(1))
    # hindi number word immediately followed by a people noun ("do log")
    for word, n in _HINDI_NUMS.items():
        if re.search(rf"\b{word}\b\s+{_PEOPLE_NOUN}", text, re.IGNORECASE):
            return n
    return None


def build_signals(
    turns: Sequence[CallerTurn],
    *,
    caller: CallerContext | None = None,
) -> ConversationSignals:
    """Distil caller turns (+ reputation) into a classifier-ready bundle."""
    caller = caller or CallerContext()
    spoken = [t for t in turns if t.text.strip() and not t.silent]
    text = " ".join(t.text for t in spoken).strip()
    low = text.lower()

    confidences = [t.confidence for t in turns]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    min_conf = min(confidences) if confidences else 0.0

    has_silence = any(t.silent or (not t.text.strip()) for t in turns) or not spoken
    # "Very short" with no real content = pocket-dial / wrong-number shaped.
    is_very_short = len(low.split()) <= 2

    return ConversationSignals(
        text=text,
        turn_count=len(turns),
        avg_confidence=round(avg_conf, 4),
        min_confidence=round(min_conf, 4),
        has_critical_kw=kw.has(low, kw.CRITICAL_RE),
        has_high_kw=kw.has(low, kw.HIGH_RE),
        has_theft_kw=kw.has(low, kw.THEFT_RE),
        has_domestic_kw=kw.has(low, kw.DOMESTIC_RE),
        has_property_kw=kw.has(low, kw.PROPERTY_RE),
        has_info_kw=kw.has(low, kw.INFO_RE),
        has_silence=has_silence,
        has_laughter=kw.has(low, kw.LAUGHTER_RE),
        has_timepass=kw.has(low, kw.TIMEPASS_RE),
        has_wrong_number=kw.has(low, kw.WRONG_NUMBER_RE),
        has_lewd=kw.has(low, kw.LEWD_RE),
        has_abuse=kw.has(low, kw.ABUSE_RE),
        is_incoherent=bool(_INCOHERENCE_RE.search(text)),
        is_very_short=is_very_short,
        has_override_cry=kw.has(low, kw.OVERRIDE_CRY_RE),
        has_override_critical=kw.has(low, kw.OVERRIDE_CRITICAL_RE),
        people_involved=_people_involved(low),
        multi_casualty=bool(_MULTI_CASUALTY_RE.search(low)),
        child_involved=bool(_CHILD_RE.search(low)),
        distress=bool(_DISTRESS_RE.search(low)),
        caller=caller,
    )
