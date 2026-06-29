"""Live-state store behaviour against fakeredis."""

import pytest

from app.db.redis_store import CallStateStore
from app.domain.enums import CallState, Severity, Speaker
from app.domain.models import Call


@pytest.mark.asyncio
async def test_set_get_round_trip(redis_client):
    store = CallStateStore(redis_client)
    call = Call(phone="+91-98100-00000")
    call.add_turn(Speaker.CALLER, "madad", confidence=0.8)
    call.incident.severity = Severity.CRITICAL

    await store.set(call)
    loaded = await store.get(call.id)
    assert loaded is not None
    assert loaded.id == call.id
    assert loaded.incident.severity is Severity.CRITICAL
    assert loaded.transcript[0].text == "madad"


@pytest.mark.asyncio
async def test_active_registry_tracks_live_calls(redis_client):
    store = CallStateStore(redis_client)
    live = Call(phone="+91-1")
    await store.set(live)
    assert live.id in await store.active_ids()

    # Terminal state => removed from the active registry on next set.
    live.state = CallState.RESOLVED
    await store.set(live)
    assert live.id not in await store.active_ids()


@pytest.mark.asyncio
async def test_delete_removes_state_and_registry(redis_client):
    store = CallStateStore(redis_client)
    call = Call(phone="+91-2")
    await store.set(call)
    await store.delete(call.id)
    assert await store.get(call.id) is None
    assert call.id not in await store.active_ids()


@pytest.mark.asyncio
async def test_ttl_is_applied(redis_client):
    store = CallStateStore(redis_client, ttl_seconds=123)
    call = Call(phone="+91-3")
    await store.set(call)
    ttl = await redis_client.ttl(store._key(call.id))
    assert 0 < ttl <= 123


@pytest.mark.asyncio
async def test_active_calls_hydrates_and_cleans_stale(redis_client):
    store = CallStateStore(redis_client)
    call = Call(phone="+91-4")
    await store.set(call)

    # Simulate the state TTL'ing out while the id lingers in the registry.
    await redis_client.delete(store._key(call.id))
    hydrated = await store.active_calls()
    assert hydrated == []
    assert call.id not in await store.active_ids()
