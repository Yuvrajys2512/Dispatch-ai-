"""Redis-backed live call state + active-call registry.

PostgreSQL is the durable record; Redis holds the *hot* state of calls that are
currently in flight so the orchestrator and dashboard can read/write it with
sub-millisecond latency. State expires on a TTL so a crashed session can't leak
a stuck "live" call forever.

The store speaks domain ``Call`` objects (serialized via Pydantic JSON) and is
client-injectable so tests can pass a fake Redis with zero infrastructure.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from redis.asyncio import Redis

from app.config import settings
from app.domain.models import Call

# Default live-state TTL: long enough for a full triage call, short enough that
# an abandoned session self-cleans. Refreshed on every set.
DEFAULT_TTL_SECONDS = 60 * 15

_STATE_KEY = "call:state:{call_id}"
_ACTIVE_SET = "calls:active"


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    """Process-wide async Redis client from settings (decodes to str)."""
    return Redis.from_url(settings.redis_url, decode_responses=True)


class CallStateStore:
    """Get/set live ``Call`` state with TTL and an active-call index."""

    def __init__(self, client: Redis, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.client = client
        self.ttl = ttl_seconds

    @staticmethod
    def _key(call_id: uuid.UUID) -> str:
        return _STATE_KEY.format(call_id=call_id)

    async def set(self, call: Call) -> None:
        """Persist live state, refresh TTL, and (de)register in the active set."""
        key = self._key(call.id)
        await self.client.set(key, call.model_dump_json(), ex=self.ttl)
        if call.is_active:
            await self.client.sadd(_ACTIVE_SET, str(call.id))
        else:
            await self.client.srem(_ACTIVE_SET, str(call.id))

    async def get(self, call_id: uuid.UUID) -> Call | None:
        raw = await self.client.get(self._key(call_id))
        return Call.model_validate_json(raw) if raw else None

    async def delete(self, call_id: uuid.UUID) -> None:
        await self.client.delete(self._key(call_id))
        await self.client.srem(_ACTIVE_SET, str(call_id))

    async def active_ids(self) -> list[uuid.UUID]:
        ids = await self.client.smembers(_ACTIVE_SET)
        return [uuid.UUID(i) for i in ids]

    async def active_calls(self) -> list[Call]:
        """Hydrate every still-present active call (skips expired entries)."""
        calls: list[Call] = []
        for call_id in await self.active_ids():
            call = await self.get(call_id)
            if call is not None:
                calls.append(call)
            else:
                # State TTL'd out from under the registry — clean the stale id.
                await self.client.srem(_ACTIVE_SET, str(call_id))
        return calls
