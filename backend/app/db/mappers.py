"""Translation between Pydantic domain objects and SQLAlchemy ORM rows.

Kept separate from the repositories so the (verbose, mechanical) field mapping
is testable in isolation and the repository methods stay readable.
"""

from __future__ import annotations

from app.db.models import CallerORM, CallORM, TranscriptTurnORM
from app.domain.models import (
    Call,
    Caller,
    GeoPoint,
    IncidentCard,
    RouteDecision,
    TranscriptTurn,
)

# --- Caller ---------------------------------------------------------------

def caller_to_orm(caller: Caller, orm: CallerORM | None = None) -> CallerORM:
    orm = orm or CallerORM(id=caller.id)
    orm.id = caller.id
    orm.phone = caller.phone
    orm.display_name = caller.display_name
    orm.total_calls = caller.total_calls
    orm.calls_today = caller.calls_today
    orm.is_blacklisted = caller.is_blacklisted
    orm.flagged_prank = caller.flagged_prank
    orm.first_seen = caller.first_seen
    orm.last_seen = caller.last_seen
    return orm


def caller_from_orm(orm: CallerORM) -> Caller:
    return Caller(
        id=orm.id,
        phone=orm.phone,
        display_name=orm.display_name,
        total_calls=orm.total_calls,
        calls_today=orm.calls_today,
        is_blacklisted=orm.is_blacklisted,
        flagged_prank=orm.flagged_prank,
        first_seen=orm.first_seen,
        last_seen=orm.last_seen,
    )


# --- TranscriptTurn -------------------------------------------------------

def turn_to_orm(turn: TranscriptTurn, call_id) -> TranscriptTurnORM:
    return TranscriptTurnORM(
        id=turn.id,
        call_id=call_id,
        seq=turn.seq,
        speaker=turn.speaker,
        text=turn.text,
        is_final=turn.is_final,
        confidence=turn.confidence,
        created_at=turn.created_at,
    )


def turn_from_orm(orm: TranscriptTurnORM) -> TranscriptTurn:
    return TranscriptTurn(
        id=orm.id,
        seq=orm.seq,
        speaker=orm.speaker,
        text=orm.text,
        is_final=orm.is_final,
        confidence=orm.confidence,
        created_at=orm.created_at,
    )


# --- Call (+ flattened incident card / route) -----------------------------

def call_to_orm(call: Call, orm: CallORM | None = None) -> CallORM:
    """Write a Call's scalar fields onto an ORM row (transcript handled separately)."""
    orm = orm or CallORM(id=call.id)
    orm.id = call.id
    orm.caller_id = call.caller_id
    orm.phone = call.phone
    orm.state = call.state
    orm.started_at = call.started_at
    orm.ended_at = call.ended_at

    inc = call.incident
    orm.caller_name = inc.caller_name
    orm.location_text = inc.location_text
    orm.location_lat = inc.location_geo.lat if inc.location_geo else None
    orm.location_lng = inc.location_geo.lng if inc.location_geo else None
    orm.incident_type = inc.incident_type
    orm.people_involved = inc.people_involved
    orm.severity = inc.severity
    orm.confidence = inc.confidence
    orm.needs_ambulance = inc.needs_ambulance
    orm.needs_police = inc.needs_police
    orm.needs_fire = inc.needs_fire
    orm.summary = inc.summary
    orm.details = inc.details

    if call.route is not None:
        orm.route_target = call.route.target
        orm.route_reason = call.route.reason
        orm.handoff = call.route.handoff
    else:
        orm.route_target = None
        orm.route_reason = None
        orm.handoff = False
    return orm


def call_from_orm(orm: CallORM, *, with_turns: bool = True) -> Call:
    geo = (
        GeoPoint(lat=orm.location_lat, lng=orm.location_lng)
        if orm.location_lat is not None and orm.location_lng is not None
        else None
    )
    incident = IncidentCard(
        caller_name=orm.caller_name,
        location_text=orm.location_text,
        location_geo=geo,
        incident_type=orm.incident_type,
        people_involved=orm.people_involved,
        severity=orm.severity,
        confidence=orm.confidence,
        needs_ambulance=orm.needs_ambulance,
        needs_police=orm.needs_police,
        needs_fire=orm.needs_fire,
        summary=orm.summary,
        details=dict(orm.details or {}),
    )
    route = None
    if orm.route_target is not None:
        route = RouteDecision(
            target=orm.route_target,
            severity=orm.severity,
            confidence=orm.confidence,
            reason=orm.route_reason or "",
            handoff=orm.handoff,
        )
    turns = (
        [turn_from_orm(t) for t in orm.turns] if with_turns else []
    )
    return Call(
        id=orm.id,
        caller_id=orm.caller_id,
        phone=orm.phone,
        state=orm.state,
        incident=incident,
        route=route,
        transcript=turns,
        started_at=orm.started_at,
        ended_at=orm.ended_at,
    )
