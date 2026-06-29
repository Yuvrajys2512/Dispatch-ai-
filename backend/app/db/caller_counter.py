"""Redis-backed rolling repeat-caller counter (Phase 6).

A prank or accidental caller who keeps dialling 112 is a junk signal: the junk
scorer weights ``calls_today >= 3``. That count has to be **live** and **rolling
per day** — it must climb as a number calls again and again *today*, then reset
tomorrow. We keep it in Redis, keyed by phone + the calendar date, so:

* the key changes at midnight → the count naturally resets each day, and
* a TTL that expires at day's end garbage-collects yesterday's keys.

**Timezone.** Days are bucketed in **IST (Asia/Kolkata)** — this is India's 112,
so "calls today" means an Indian calendar day, not UTC. The bucket date and the
end-of-day TTL are both computed in IST.

Like :class:`~app.db.redis_store.CallStateStore`, the client is injectable so the
unit tests run against ``fakeredis`` with zero infrastructure.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

# India's 112 — bucket "today" on the Indian calendar day, not UTC.
BUCKET_TZ = ZoneInfo("Asia/Kolkata")

_KEY = "caller:calls:{phone}:{day}"
# Small grace beyond midnight so a call right at the day boundary doesn't lose
# its key before anything reads it; the date-keying already does the real reset.
_TTL_GRACE_SECONDS = 60 * 60


def _now_ist(now: datetime | None = None) -> datetime:
    now = now or datetime.now(BUCKET_TZ)
    # Accept naive/aware datetimes; interpret/convert into IST for bucketing.
    if now.tzinfo is None:
        return now.replace(tzinfo=BUCKET_TZ)
    return now.astimezone(BUCKET_TZ)


def _seconds_until_eod(now_ist: datetime) -> int:
    """Seconds from ``now`` until the next IST midnight, plus a grace window."""
    next_midnight = (now_ist + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int((next_midnight - now_ist).total_seconds()) + _TTL_GRACE_SECONDS


class CallerCallCounter:
    """Rolling per-day call counter for a phone number, in Redis."""

    def __init__(self, client: Redis) -> None:
        self.client = client

    @staticmethod
    def _key(phone: str, now_ist: datetime) -> str:
        return _KEY.format(phone=phone, day=now_ist.date().isoformat())

    async def increment(self, phone: str, *, now: datetime | None = None) -> int:
        """Count this call against today's bucket and return the new total.

        The first call of the day returns ``1``; the third returns ``3`` (which
        is where the junk scorer's repeat-caller weight starts to fire). The TTL
        is (re)set to expire at the end of the IST day on every increment.
        """
        now_ist = _now_ist(now)
        key = self._key(phone, now_ist)
        count = await self.client.incr(key)
        await self.client.expire(key, _seconds_until_eod(now_ist))
        return int(count)

    async def get(self, phone: str, *, now: datetime | None = None) -> int:
        """Today's call count for ``phone`` (0 if it hasn't called today)."""
        now_ist = _now_ist(now)
        raw = await self.client.get(self._key(phone, now_ist))
        return int(raw) if raw is not None else 0

    async def seed(self, phone: str, count: int, *, now: datetime | None = None) -> None:
        """Set today's raw count (for the simulator/demo to replay prior calls).

        Production never calls this — the counter only ever climbs via
        :meth:`increment`. The simulator uses it to reproduce a scenario's
        scripted "already called N times today" reputation through the live
        store, so a subsequent :meth:`increment` lands on the intended total.
        """
        now_ist = _now_ist(now)
        key = self._key(phone, now_ist)
        await self.client.set(key, count, ex=_seconds_until_eod(now_ist))
