"""Rolling repeat-caller counter behaviour against fakeredis."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.db.caller_counter import BUCKET_TZ, CallerCallCounter

_PHONE = "+91-63000-50006"


@pytest.mark.asyncio
async def test_increment_climbs_and_fires_on_third_call(redis_client):
    counter = CallerCallCounter(redis_client)
    assert await counter.get(_PHONE) == 0
    assert await counter.increment(_PHONE) == 1
    assert await counter.increment(_PHONE) == 2
    # The third call of the day is where the junk repeat-weight starts to fire.
    assert await counter.increment(_PHONE) == 3
    assert await counter.get(_PHONE) == 3


@pytest.mark.asyncio
async def test_counter_is_per_number(redis_client):
    counter = CallerCallCounter(redis_client)
    await counter.increment("+91-1")
    await counter.increment("+91-1")
    await counter.increment("+91-2")
    assert await counter.get("+91-1") == 2
    assert await counter.get("+91-2") == 1


@pytest.mark.asyncio
async def test_rolls_over_at_day_boundary(redis_client):
    counter = CallerCallCounter(redis_client)
    day1 = datetime(2026, 6, 24, 23, 0, tzinfo=BUCKET_TZ)
    day2 = datetime(2026, 6, 25, 1, 0, tzinfo=BUCKET_TZ)

    await counter.increment(_PHONE, now=day1)
    await counter.increment(_PHONE, now=day1)
    assert await counter.get(_PHONE, now=day1) == 2
    # A new IST day is a fresh bucket — the count resets.
    assert await counter.get(_PHONE, now=day2) == 0
    assert await counter.increment(_PHONE, now=day2) == 1


@pytest.mark.asyncio
async def test_ttl_expires_at_end_of_day(redis_client):
    counter = CallerCallCounter(redis_client)
    morning = datetime(2026, 6, 24, 9, 0, tzinfo=BUCKET_TZ)
    await counter.increment(_PHONE, now=morning)
    key = counter._key(_PHONE, morning)
    ttl = await redis_client.ttl(key)
    # Expires sometime after the remaining ~15h of the day, never longer than a
    # day-plus-grace.
    assert 0 < ttl <= 26 * 60 * 60


@pytest.mark.asyncio
async def test_seed_then_increment_lands_on_total(redis_client):
    counter = CallerCallCounter(redis_client)
    # The simulator replays "already called 4 times today" by seeding 4, so the
    # call's own increment lands on 5.
    await counter.seed(_PHONE, 4)
    assert await counter.get(_PHONE) == 4
    assert await counter.increment(_PHONE) == 5


@pytest.mark.asyncio
async def test_utc_input_is_bucketed_in_ist(redis_client):
    counter = CallerCallCounter(redis_client)
    # 2026-06-24 20:00 UTC == 2026-06-25 01:30 IST → counts on the 25th in IST.
    utc = datetime(2026, 6, 24, 20, 0, tzinfo=ZoneInfo("UTC"))
    await counter.increment(_PHONE, now=utc)
    ist_25 = datetime(2026, 6, 25, 1, 30, tzinfo=BUCKET_TZ)
    assert await counter.get(_PHONE, now=ist_25) == 1
