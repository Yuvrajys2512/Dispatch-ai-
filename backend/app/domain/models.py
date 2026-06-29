"""Pydantic v2 domain models — the canonical, typed vocabulary of Dispatch AI.

One schema set, shared across the API, the conversation agent, the realtime
event stream, and (mapped onto ORM rows) persistence. Models are deliberately
free of any infrastructure concerns: no SQLAlchemy, no Redis, no FastAPI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    CallState,
    IncidentType,
    RouteTarget,
    Severity,
    Speaker,
)

# Safety threshold (spec §4): below this AI confidence we must hand off to a
# human. The *enforcement* (and its tests) lands in Phase 3 — this constant is
# the single source of truth both phases share.
CONFIDENCE_HANDOFF_THRESHOLD: float = 0.80


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


class GeoPoint(BaseModel):
    """Optional resolved coordinates for a location."""

    model_config = ConfigDict(frozen=True)

    lat: float = Field(ge=-90.0, le=90.0)
    lng: float = Field(ge=-180.0, le=180.0)


class Caller(BaseModel):
    """A phone number that has called 112, with rolling reputation signals.

    Caller history (repeat-prank tracking, blacklist) is what lets the junk
    scorer in Phase 6 weigh a number. Identity is the E.164-ish phone string.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: uuid.UUID = Field(default_factory=_new_id)
    phone: str = Field(description="Caller's number, e.g. +91-98xxx")
    display_name: str | None = None
    total_calls: int = Field(default=0, ge=0)
    calls_today: int = Field(default=0, ge=0)
    is_blacklisted: bool = False
    flagged_prank: bool = False
    first_seen: datetime = Field(default_factory=_utcnow)
    last_seen: datetime = Field(default_factory=_utcnow)


class TranscriptTurn(BaseModel):
    """A single utterance in the conversation.

    Turns are streaming-shaped: a turn may be `is_final=False` (a partial,
    in-flight ASR hypothesis) before its finalized version arrives. `confidence`
    is the ASR/agent confidence for this turn, 0–1.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: uuid.UUID = Field(default_factory=_new_id)
    seq: int = Field(ge=0, description="Monotonic turn index within the call")
    speaker: Speaker
    text: str
    is_final: bool = True
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_utcnow)


class IncidentCard(BaseModel):
    """The structured triage output, filled progressively across the call.

    Mirrors the dispatcher dashboard card (spec §6). Every field is optional at
    the start of a call and fills in as the agent extracts it; `severity` and
    `confidence` drive routing.
    """

    model_config = ConfigDict(validate_assignment=True)

    caller_name: str | None = None
    location_text: str | None = None
    location_geo: GeoPoint | None = None
    incident_type: IncidentType = IncidentType.UNKNOWN
    people_involved: int | None = Field(default=None, ge=0)
    severity: Severity = Severity.MEDIUM
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_ambulance: bool = False
    needs_police: bool = False
    needs_fire: bool = False
    summary: str | None = None
    details: dict[str, object] = Field(default_factory=dict)

    @property
    def requires_handoff(self) -> bool:
        """Safety surface: HIGH+ severity OR sub-threshold confidence.

        The authoritative, test-gated enforcement is wired in Phase 3; this
        read-only helper exists so callers don't re-derive the rule.
        """
        return (
            self.severity >= Severity.HIGH
            or self.confidence < CONFIDENCE_HANDOFF_THRESHOLD
        )


class RouteDecision(BaseModel):
    """The terminal triage verdict for a call."""

    model_config = ConfigDict(validate_assignment=True)

    target: RouteTarget
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    handoff: bool = False
    decided_at: datetime = Field(default_factory=_utcnow)


class Call(BaseModel):
    """A single emergency call session — the aggregate root.

    Holds the live state-machine position, the growing transcript, the current
    incident card, and (once triaged) the route decision. This is the object the
    orchestrator owns per call and the dashboard renders.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: uuid.UUID = Field(default_factory=_new_id)
    caller_id: uuid.UUID | None = None
    phone: str
    state: CallState = CallState.GREETING
    incident: IncidentCard = Field(default_factory=IncidentCard)
    route: RouteDecision | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        """Wall-clock seconds from start to end (or now if still live)."""
        end = self.ended_at or _utcnow()
        return (end - self.started_at).total_seconds()

    @property
    def is_active(self) -> bool:
        return self.ended_at is None and not self.state.is_terminal

    def add_turn(
        self,
        speaker: Speaker,
        text: str,
        *,
        is_final: bool = True,
        confidence: float | None = None,
    ) -> TranscriptTurn:
        """Append a turn with the next sequence number and return it."""
        turn = TranscriptTurn(
            seq=len(self.transcript),
            speaker=speaker,
            text=text,
            is_final=is_final,
            confidence=confidence,
        )
        self.transcript.append(turn)
        return turn
