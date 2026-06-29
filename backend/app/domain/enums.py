"""Core enumerations — the canonical vocabulary of the triage system.

These values are shared across the API, the agent, persistence, and the
WebSocket event schema. They are intentionally string-valued so they serialize
cleanly to JSON and read well in the database.
"""

from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    """Triage severity, highest-to-lowest urgency.

    Ordering matters: the safety rule "severity >= HIGH => instant handoff"
    relies on :meth:`rank` to compare levels. JUNK is the only non-emergency
    bucket and is auto-resolvable.
    """

    CRITICAL = "CRITICAL"  # auto-escalate immediately, no waiting
    HIGH = "HIGH"  # priority queue / instant handoff
    MEDIUM = "MEDIUM"  # standard queue
    LOW = "LOW"  # AI may resolve (info request, non-emergency)
    JUNK = "JUNK"  # auto-resolve without operator

    @property
    def rank(self) -> int:
        """Numeric urgency, CRITICAL=4 … JUNK=0. Higher = more urgent."""
        return _SEVERITY_RANK[self]

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank >= other.rank
        return NotImplemented

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank > other.rank
        return NotImplemented

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank <= other.rank
        return NotImplemented

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if isinstance(other, Severity):
            return self.rank < other.rank
        return NotImplemented


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.JUNK: 0,
}


class CallState(str, Enum):
    """State-machine position of a call (spec §3).

    GREETING → INCIDENT_TYPE → LOCATION → DETAILS → SEVERITY_SCORE → ROUTE,
    then a terminal state. ROUTED/RESOLVED/ABANDONED/HANDED_OVER are terminal.
    """

    GREETING = "GREETING"
    INCIDENT_TYPE = "INCIDENT_TYPE"
    LOCATION = "LOCATION"
    DETAILS = "DETAILS"
    SEVERITY_SCORE = "SEVERITY_SCORE"
    ROUTE = "ROUTE"
    # terminal states
    ROUTED = "ROUTED"  # queued with a pre-filled card for an operator
    HANDED_OVER = "HANDED_OVER"  # operator took the live call
    RESOLVED = "RESOLVED"  # closed by AI (junk auto-resolve / info request)
    ABANDONED = "ABANDONED"  # caller hung up before triage completed

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATES


_TERMINAL_STATES: frozenset[CallState] = frozenset(
    {
        CallState.ROUTED,
        CallState.HANDED_OVER,
        CallState.RESOLVED,
        CallState.ABANDONED,
    }
)


class IncidentType(str, Enum):
    """Classified nature of the incident (spec §3 INCIDENT_TYPE)."""

    ACCIDENT = "ACCIDENT"
    ASSAULT = "ASSAULT"
    THEFT = "THEFT"
    FIRE = "FIRE"
    MEDICAL = "MEDICAL"
    DOMESTIC = "DOMESTIC"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"  # not yet determined


class RouteTarget(str, Enum):
    """Where a triaged call is sent (spec §3 ROUTE)."""

    OPERATOR_IMMEDIATE = "OPERATOR_IMMEDIATE"  # CRITICAL/HIGH or low confidence
    OPERATOR_QUEUE = "OPERATOR_QUEUE"  # MEDIUM — queued with pre-filled card
    AI_RESOLVE = "AI_RESOLVE"  # LOW — AI may handle
    AUTO_RESOLVE = "AUTO_RESOLVE"  # JUNK — closed, never touches an operator


class Speaker(str, Enum):
    """Who produced a transcript turn."""

    CALLER = "CALLER"
    AI = "AI"
    OPERATOR = "OPERATOR"
