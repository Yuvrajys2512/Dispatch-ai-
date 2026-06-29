"""Realtime layer — the typed event schema and the WebSocket fan-out hub.

The orchestrator (:mod:`app.orchestrator`) emits :class:`Event` objects into an
:class:`EventHub`; WebSocket clients subscribe to the hub and receive the ordered
stream. See :mod:`app.realtime.events` for the schema and :mod:`app.realtime.hub`
for the fan-out.
"""

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

__all__ = [
    "CallEnded",
    "CallStarted",
    "Event",
    "EventHub",
    "IncidentUpdated",
    "OperatorTakeover",
    "RouteDecided",
    "SeverityChanged",
    "TranscriptFinal",
    "TranscriptPartial",
    "default_hub",
]
