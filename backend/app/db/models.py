"""SQLAlchemy ORM models (calls, callers, transcript_turns, events).

Column types are chosen to be portable across PostgreSQL (production) and
SQLite (the infra-free test suite): ``Uuid`` for keys, timezone-aware
``DateTime``, ``JSON`` for semi-structured payloads, and non-native enums
(VARCHAR + CHECK) so the same DDL works on both backends.

These rows are the persisted projection of the Pydantic domain models in
``app.domain``; mapping between the two lives in ``app.db.repositories``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import (
    CallState,
    IncidentType,
    RouteTarget,
    Severity,
    Speaker,
)


def _enum(py_enum: type) -> Enum:
    """Portable string enum column (VARCHAR + CHECK, not a native PG enum)."""
    return Enum(py_enum, native_enum=False, length=32, validate_strings=True)


class CallerORM(Base):
    __tablename__ = "callers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    total_calls: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    calls_today: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_blacklisted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    flagged_prank: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    calls: Mapped[list[CallORM]] = relationship(
        back_populates="caller", cascade="all, delete-orphan"
    )


class CallORM(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    caller_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("callers.id", ondelete="SET NULL"), index=True
    )
    phone: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[CallState] = mapped_column(_enum(CallState), default=CallState.GREETING)

    # Flattened incident card (the dashboard reads these directly).
    caller_name: Mapped[str | None] = mapped_column(String(128))
    location_text: Mapped[str | None] = mapped_column(Text)
    location_lat: Mapped[float | None] = mapped_column(Float)
    location_lng: Mapped[float | None] = mapped_column(Float)
    incident_type: Mapped[IncidentType] = mapped_column(
        _enum(IncidentType), default=IncidentType.UNKNOWN
    )
    people_involved: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[Severity] = mapped_column(_enum(Severity), default=Severity.MEDIUM)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    needs_ambulance: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_police: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_fire: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    # Route decision (nullable until triaged).
    route_target: Mapped[RouteTarget | None] = mapped_column(_enum(RouteTarget))
    route_reason: Mapped[str | None] = mapped_column(Text)
    handoff: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    caller: Mapped[CallerORM | None] = relationship(back_populates="calls")
    turns: Mapped[list[TranscriptTurnORM]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="TranscriptTurnORM.seq",
    )
    events: Mapped[list[EventORM]] = relationship(
        back_populates="call",
        cascade="all, delete-orphan",
        order_by="EventORM.created_at",
    )


class TranscriptTurnORM(Base):
    __tablename__ = "transcript_turns"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[Speaker] = mapped_column(_enum(Speaker))
    text: Mapped[str] = mapped_column(Text)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    call: Mapped[CallORM] = relationship(back_populates="turns")


class EventORM(Base):
    """Append-only audit/event log per call (drives analytics + replay)."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    call: Mapped[CallORM] = relationship(back_populates="events")
