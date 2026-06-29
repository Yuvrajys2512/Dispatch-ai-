"""Infra-free fixtures for the data-layer tests.

The DB tests run against an in-memory async SQLite database (shared across the
test via ``StaticPool``) and the Redis tests against ``fakeredis`` — so
``pytest tests/db`` is green with no Docker, no Postgres, no Redis. The same
repository/store code runs against real PostgreSQL + Redis in the seed demo and
in production; only the engine/client differ.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401  (register tables on Base.metadata)
from app.db.base import Base


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[fake_aioredis.FakeRedis]:
    client = fake_aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()
