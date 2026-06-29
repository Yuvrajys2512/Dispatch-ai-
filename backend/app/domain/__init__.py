"""Domain package — the typed, infrastructure-free vocabulary of Dispatch AI."""

from app.domain.enums import (
    CallState,
    IncidentType,
    RouteTarget,
    Severity,
    Speaker,
)
from app.domain.models import (
    CONFIDENCE_HANDOFF_THRESHOLD,
    Call,
    Caller,
    GeoPoint,
    IncidentCard,
    RouteDecision,
    TranscriptTurn,
)

__all__ = [
    "CONFIDENCE_HANDOFF_THRESHOLD",
    "Call",
    "CallState",
    "Caller",
    "GeoPoint",
    "IncidentCard",
    "IncidentType",
    "RouteDecision",
    "RouteTarget",
    "Severity",
    "Speaker",
    "TranscriptTurn",
]
