"""Repository round-trips against an in-memory async SQLite database."""

import pytest

from app.db.repositories import CallerRepository, CallRepository
from app.domain.enums import IncidentType, RouteTarget, Severity, Speaker
from app.domain.models import Call, GeoPoint, RouteDecision


@pytest.mark.asyncio
async def test_caller_get_or_create_is_idempotent(session):
    repo = CallerRepository(session)
    a = await repo.get_or_create("+91-98100-00001")
    b = await repo.get_or_create("+91-98100-00001")
    assert a.id == b.id
    found = await repo.get_by_phone("+91-98100-00001")
    assert found is not None and found.id == a.id


@pytest.mark.asyncio
async def test_caller_lookup_miss_returns_none(session):
    repo = CallerRepository(session)
    assert await repo.get_by_phone("+91-00000-00000") is None


@pytest.mark.asyncio
async def test_set_reputation_creates_and_flags(session):
    repo = CallerRepository(session)
    # Blacklisting an unseen number creates the row.
    updated = await repo.set_reputation("+91-63000-50007", is_blacklisted=True)
    assert updated.is_blacklisted is True
    assert updated.flagged_prank is False

    found = await repo.get_by_phone("+91-63000-50007")
    assert found is not None and found.is_blacklisted is True


@pytest.mark.asyncio
async def test_set_reputation_updates_only_given_flags(session):
    repo = CallerRepository(session)
    await repo.set_reputation("+91-90000-60004", flagged_prank=True)
    # A later blacklist call must not clear the earlier flagged-prank flag.
    updated = await repo.set_reputation("+91-90000-60004", is_blacklisted=True)
    assert updated.is_blacklisted is True
    assert updated.flagged_prank is True


@pytest.mark.asyncio
async def test_create_call_with_turns_reads_back(session):
    callers = CallerRepository(session)
    calls = CallRepository(session)
    caller = await callers.get_or_create("+91-98100-00002")

    call = Call(caller_id=caller.id, phone=caller.phone)
    call.add_turn(Speaker.AI, "112 emergency. Kya hua?")
    call.add_turn(Speaker.CALLER, "Accident ho gaya", confidence=0.9)
    created = await calls.create(call)

    reloaded = await calls.get(created.id)
    assert reloaded is not None
    assert reloaded.phone == "+91-98100-00002"
    assert [t.text for t in reloaded.transcript] == [
        "112 emergency. Kya hua?",
        "Accident ho gaya",
    ]
    assert reloaded.transcript[1].confidence == 0.9


@pytest.mark.asyncio
async def test_update_persists_incident_and_appends_only_new_turns(session):
    calls = CallRepository(session)
    call = Call(phone="+91-70000-00003")
    call.add_turn(Speaker.AI, "greeting")
    call = await calls.create(call)

    # Mutate incident + append one more turn, then update.
    call.incident.incident_type = IncidentType.ACCIDENT
    call.incident.severity = Severity.CRITICAL
    call.incident.confidence = 0.93
    call.incident.location_geo = GeoPoint(lat=28.6, lng=77.4)
    call.incident.location_text = "NH-24"
    call.add_turn(Speaker.CALLER, "do log ghayal hain", confidence=0.88)
    updated = await calls.update(call)

    assert len(updated.transcript) == 2  # not duplicated
    assert updated.incident.severity is Severity.CRITICAL
    assert updated.incident.location_geo == GeoPoint(lat=28.6, lng=77.4)
    assert updated.incident.requires_handoff

    # A second update with no new turns keeps the count stable.
    again = await calls.update(updated)
    assert len(again.transcript) == 2


@pytest.mark.asyncio
async def test_route_decision_persists(session):
    calls = CallRepository(session)
    call = Call(phone="+91-1")
    call.route = RouteDecision(
        target=RouteTarget.OPERATOR_IMMEDIATE,
        severity=Severity.CRITICAL,
        confidence=0.95,
        reason="severity>=HIGH",
        handoff=True,
    )
    call.incident.severity = Severity.CRITICAL
    call.incident.confidence = 0.95
    created = await calls.create(call)

    reloaded = await calls.get(created.id)
    assert reloaded.route is not None
    assert reloaded.route.target is RouteTarget.OPERATOR_IMMEDIATE
    assert reloaded.route.handoff is True


@pytest.mark.asyncio
async def test_append_turn_fast_path_and_events(session):
    calls = CallRepository(session)
    call = await calls.create(Call(phone="+91-2"))
    turn = call.add_turn(Speaker.CALLER, "streamed", confidence=0.7)
    await calls.append_turn(call.id, turn)
    await calls.log_event(call.id, "transcript.final", {"seq": turn.seq})

    reloaded = await calls.get(call.id)
    assert [t.text for t in reloaded.transcript] == ["streamed"]


@pytest.mark.asyncio
async def test_list_for_caller(session):
    callers = CallerRepository(session)
    calls = CallRepository(session)
    caller = await callers.get_or_create("+91-55555-00000")
    await calls.create(Call(caller_id=caller.id, phone=caller.phone))
    await calls.create(Call(caller_id=caller.id, phone=caller.phone))

    history = await calls.list_for_caller(caller.id)
    assert len(history) == 2
