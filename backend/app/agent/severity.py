"""Severity classifier — the real rule engine (spec §4).

Maps conversation signals to a :class:`Severity` using the spec's tiers. This is
the authoritative severity decision; it deliberately does *not* trust the mock
LLM's guess (the mock only does crude keyword extraction). The order of checks
encodes the urgency ladder: any life-threat word → CRITICAL; else a serious
medical/violence word → HIGH; else theft/property/dispute → MEDIUM; else an
info-request → LOW; else MEDIUM as the conservative default (an un-classified
call that *spoke* is treated as a real-but-unknown emergency, never as junk —
junk is decided separately and only when there is no emergency content).

The returned :class:`SeverityVerdict` carries the human-readable reasons so the
dashboard and tests can see *why* a level was chosen.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.signals import ConversationSignals
from app.domain.enums import IncidentType, Severity


@dataclass(frozen=True)
class SeverityVerdict:
    severity: Severity
    incident_type: IncidentType
    needs_ambulance: bool
    needs_police: bool
    needs_fire: bool
    reasons: tuple[str, ...]


def _incident_type(s: ConversationSignals) -> IncidentType:
    low = s.text.lower()
    if "accident" in low or "takkar" in low:
        return IncidentType.ACCIDENT
    if s.has_critical_kw and ("aag" in low or "fire" in low or "blast" in low):
        return IncidentType.FIRE
    if s.has_theft_kw:
        return IncidentType.THEFT
    if any(w in low for w in (
        "dard", "seene", "saans", "behosh", "daura", "mirgi", "stroke",
        "lakwa", "saap", "saanp", "snake", "medical", "delivery", "prasav",
        "doob", "current", "gas",
    )):
        return IncidentType.MEDICAL
    if any(w in low for w in (
        "maar", "peet", "loot", "luut", "robbery", "assault", "hamla",
        "kidnap", "agwa", "stab", "ghonp", "goli", "gun", "knife", "chaaku",
    )):
        return IncidentType.ASSAULT
    if s.has_domestic_kw or "ghar mein maar" in low or "pati" in low:
        return IncidentType.DOMESTIC
    if s.text.strip():
        return IncidentType.OTHER
    return IncidentType.UNKNOWN


def classify_severity(s: ConversationSignals) -> SeverityVerdict:
    """Assign the spec §4 tier from signals alone (junk handled elsewhere)."""
    reasons: list[str] = []
    incident = _incident_type(s)

    if s.has_critical_kw:
        severity = Severity.CRITICAL
        reasons.append("life-threat keyword")
    elif s.multi_casualty:
        severity = Severity.CRITICAL
        reasons.append("multiple casualties mentioned")
    elif s.has_high_kw:
        severity = Severity.HIGH
        reasons.append("serious medical / violence keyword")
    elif s.has_theft_kw:
        severity = Severity.MEDIUM
        reasons.append("theft reported")
    elif s.has_property_kw or s.has_domestic_kw:
        severity = Severity.MEDIUM
        reasons.append("property / dispute")
    elif s.has_info_kw:
        severity = Severity.LOW
        reasons.append("information request")
    else:
        severity = Severity.MEDIUM
        reasons.append("unclassified spoken call (conservative default)")

    # A child in danger or audible distress bumps a sub-critical emergency up
    # one notch (spec §4: child's voice / screaming → CRITICAL).
    if severity >= Severity.HIGH and (s.child_involved or s.distress):
        if severity is Severity.HIGH:
            severity = Severity.CRITICAL
            reasons.append("child / distress escalates HIGH→CRITICAL")

    needs_ambulance = incident in (IncidentType.ACCIDENT, IncidentType.MEDICAL) or any(
        w in s.text.lower()
        for w in ("ghayal", "injured", "khoon", "blood", "behosh", "saans", "ambulance")
    )
    needs_fire = incident is IncidentType.FIRE or any(
        w in s.text.lower() for w in ("aag", "fire", "blast", "dhamaka", "gas leak")
    )
    needs_police = incident in (
        IncidentType.ACCIDENT,
        IncidentType.THEFT,
        IncidentType.ASSAULT,
        IncidentType.DOMESTIC,
    )

    return SeverityVerdict(
        severity=severity,
        incident_type=incident,
        needs_ambulance=needs_ambulance,
        needs_police=needs_police,
        needs_fire=needs_fire,
        reasons=tuple(reasons),
    )
