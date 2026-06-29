"""Seed fixtures + a live round-trip demo for the Phase 1 data layer.

Two things live here:

* :data:`SEED_CALLERS` / :func:`build_seed_calls` — deterministic sample data
  used both for local dev seeding and as a shared fixture for tests.
* :func:`demo` — the Phase 1 "verifiable output" script: against the configured
  PostgreSQL + Redis (``docker compose up`` first), it creates a call, appends
  transcript turns, reads it back from Postgres, and stores/reads live state in
  Redis.

Run it with:  ``python -m app.db.seed``
"""

from __future__ import annotations

import asyncio

from app.db.redis_store import CallStateStore, get_redis
from app.db.repositories import CallerRepository, CallRepository
from app.db.session import session_scope
from app.domain.enums import IncidentType, RouteTarget, Severity, Speaker
from app.domain.models import Call, Caller, GeoPoint, IncidentCard, RouteDecision

# --- Deterministic seed data ---------------------------------------------

SEED_CALLERS: list[Caller] = [
    Caller(phone="+91-98100-00001", display_name="Unknown", total_calls=1, calls_today=1),
    Caller(phone="+91-70000-00002", display_name="Unknown", total_calls=4, calls_today=3),
    Caller(
        phone="+91-63000-00003",
        display_name="Repeat prank",
        total_calls=9,
        calls_today=3,
        flagged_prank=True,
    ),
]


def build_seed_calls(callers: list[Caller]) -> list[Call]:
    """A representative spread of calls (critical, medium, junk)."""
    accident = Call(
        caller_id=callers[0].id,
        phone=callers[0].phone,
        incident=IncidentCard(
            caller_name="Rohit",
            location_text="NH-24 near Ghaziabad toll plaza",
            location_geo=GeoPoint(lat=28.6692, lng=77.4538),
            incident_type=IncidentType.ACCIDENT,
            people_involved=2,
            severity=Severity.CRITICAL,
            confidence=0.94,
            needs_ambulance=True,
            needs_police=True,
            summary="Two-car collision, 2 injured, one bleeding.",
        ),
        route=RouteDecision(
            target=RouteTarget.OPERATOR_IMMEDIATE,
            severity=Severity.CRITICAL,
            confidence=0.94,
            reason="severity>=HIGH",
            handoff=True,
        ),
    )
    accident.add_turn(Speaker.AI, "112 emergency. Kya hua? Aap kahan hain?")
    accident.add_turn(
        Speaker.CALLER, "Accident ho gaya, do log ghayal hain!", confidence=0.91
    )

    theft = Call(
        caller_id=callers[1].id,
        phone=callers[1].phone,
        incident=IncidentCard(
            location_text="Sector 62, Noida — near Metro station",
            incident_type=IncidentType.THEFT,
            severity=Severity.MEDIUM,
            confidence=0.87,
            needs_police=True,
            summary="Phone snatched 10 minutes ago.",
        ),
        route=RouteDecision(
            target=RouteTarget.OPERATOR_QUEUE,
            severity=Severity.MEDIUM,
            confidence=0.87,
            reason="medium severity, confident",
        ),
    )
    theft.add_turn(Speaker.AI, "112 emergency, aapki kya problem hai?")
    theft.add_turn(Speaker.CALLER, "Mera phone chori ho gaya", confidence=0.88)

    junk = Call(
        caller_id=callers[2].id,
        phone=callers[2].phone,
        incident=IncidentCard(severity=Severity.JUNK, confidence=0.97),
        route=RouteDecision(
            target=RouteTarget.AUTO_RESOLVE,
            severity=Severity.JUNK,
            confidence=0.97,
            reason="silent call, repeat caller (3rd today)",
        ),
    )
    junk.add_turn(Speaker.AI, "112 emergency. Hello? Aap sun rahe hain?")

    return [accident, theft, junk]


# --- Live round-trip demo (the Phase 1 verifiable output) -----------------

async def demo() -> None:
    store = CallStateStore(get_redis())

    async with session_scope() as session:
        callers_repo = CallerRepository(session)
        calls_repo = CallRepository(session)

        # 1. Caller lookup-or-create by phone.
        caller = await callers_repo.get_or_create("+91-98100-12345")
        print(f"caller: {caller.phone} (id={caller.id})")

        # 2. Create a call.
        call = Call(caller_id=caller.id, phone=caller.phone)
        call = await calls_repo.create(call)
        print(f"created call {call.id} state={call.state.value}")

        # 3. Append transcript turns.
        call.add_turn(Speaker.AI, "112 emergency. Kya hua? Aap kahan hain?")
        call.add_turn(Speaker.CALLER, "Accident ho gaya, madad chahiye!", confidence=0.9)
        call.incident.incident_type = IncidentType.ACCIDENT
        call.incident.severity = Severity.CRITICAL
        call.incident.confidence = 0.92
        call = await calls_repo.update(call)
        print(f"appended {len(call.transcript)} turns")

        # 4. Read it back from Postgres.
        reloaded = await calls_repo.get(call.id)
        assert reloaded is not None
        assert len(reloaded.transcript) == 2
        assert reloaded.incident.severity is Severity.CRITICAL
        print(
            f"read back from Postgres: {len(reloaded.transcript)} turns, "
            f"severity={reloaded.incident.severity.value}, "
            f"requires_handoff={reloaded.incident.requires_handoff}"
        )

        # 5. Store + read live state in Redis.
        await store.set(reloaded)
        live = await store.get(reloaded.id)
        assert live is not None and live.id == reloaded.id
        active = await store.active_ids()
        print(f"redis live state ok; active calls={len(active)}")

    await store.client.aclose()
    print("Phase 1 round-trip OK ✅")


async def seed() -> None:
    """Insert the deterministic sample data for local dashboard dev."""
    async with session_scope() as session:
        callers_repo = CallerRepository(session)
        calls_repo = CallRepository(session)
        for c in SEED_CALLERS:
            await callers_repo.save(c)
        for call in build_seed_calls(SEED_CALLERS):
            await calls_repo.create(call)
    print(f"seeded {len(SEED_CALLERS)} callers and 3 calls")


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "demo"
    asyncio.run(seed() if target == "seed" else demo())
