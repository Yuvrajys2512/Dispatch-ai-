"""Realtime event schema — the typed, ordered stream the orchestrator emits.

Every meaningful moment in a call's life becomes one of these events. They are
Pydantic models with a discriminated ``type`` tag, a stable ``call_id``, a
**per-call monotonic ``seq``** (so a subscriber can detect gaps/reordering), and
a ``ts`` wall-clock timestamp. The :data:`Event` union is what the WebSocket hub
fans out and what the dashboard (Phase 5) renders.

The eight event types, in the order they typically occur over a call::

    call.started → transcript.partial* → transcript.final → incident.updated
                 → severity.changed? → … → route.decided → call.ended
    operator.takeover  (out-of-band, when a human takes the live call)

Only ``call.started`` (first) and ``call.ended`` (last) are guaranteed for every
call; the middle events fire as the conversation produces them.
"""

from __future__ import annotations

import time
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.domain.enums import CallState, RouteTarget, Severity
from app.domain.models import IncidentCard


def _now() -> float:
    return time.time()


class _BaseEvent(BaseModel):
    """Fields shared by every event."""

    call_id: str
    seq: int = Field(ge=0, description="Per-call monotonic event index")
    ts: float = Field(default_factory=_now, description="Unix timestamp (seconds)")


class CallStarted(_BaseEvent):
    type: Literal["call.started"] = "call.started"
    phone: str
    scenario: str | None = None


class TranscriptPartial(_BaseEvent):
    type: Literal["transcript.partial"] = "transcript.partial"
    text: str
    confidence: float


class TranscriptFinal(_BaseEvent):
    type: Literal["transcript.final"] = "transcript.final"
    text: str
    confidence: float
    turn_seq: int = Field(ge=0, description="Index of this turn in the transcript")


class IncidentUpdated(_BaseEvent):
    type: Literal["incident.updated"] = "incident.updated"
    incident: IncidentCard


class SeverityChanged(_BaseEvent):
    type: Literal["severity.changed"] = "severity.changed"
    previous: Severity | None
    current: Severity


class RouteDecided(_BaseEvent):
    type: Literal["route.decided"] = "route.decided"
    target: RouteTarget
    severity: Severity
    confidence: float
    reason: str
    handoff: bool


class CallEnded(_BaseEvent):
    type: Literal["call.ended"] = "call.ended"
    final_state: CallState
    duration_seconds: float


class OperatorTakeover(_BaseEvent):
    type: Literal["operator.takeover"] = "operator.takeover"
    reason: str = "manual operator takeover"


# Discriminated union: parse/serialize any event by its ``type`` tag.
Event = Annotated[
    CallStarted
    | TranscriptPartial
    | TranscriptFinal
    | IncidentUpdated
    | SeverityChanged
    | RouteDecided
    | CallEnded
    | OperatorTakeover,
    Field(discriminator="type"),
]

__all__ = [
    "CallEnded",
    "CallStarted",
    "Event",
    "IncidentUpdated",
    "OperatorTakeover",
    "RouteDecided",
    "SeverityChanged",
    "TranscriptFinal",
    "TranscriptPartial",
]
