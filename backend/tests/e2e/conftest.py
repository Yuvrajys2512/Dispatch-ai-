"""Infra-free fixtures for the end-to-end orchestrator tests.

Same philosophy as ``tests/db/conftest.py``: an in-memory async SQLite database
(shared via ``StaticPool``) stands in for PostgreSQL and ``fakeredis`` for Redis,
so a full simulated call lifecycle runs with **no Docker**. DB writes from
concurrent calls are serialized by an :class:`asyncio.Lock` inside the session
factory — SQLite's single shared connection can't take truly-concurrent writers,
but the rest of the pipeline (ASR/agent/TTS/events) still runs concurrently, so
the concurrency tests are real. Real PostgreSQL (Phase 7) needs no such lock.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401  (register tables on Base.metadata)
from app.db.base import Base
from app.db.redis_store import CallStateStore
from app.orchestrator.registry import SessionRegistry
from app.orchestrator.session import SessionFactory
from app.realtime.hub import EventHub


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> SessionFactory:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    lock = asyncio.Lock()

    @asynccontextmanager
    async def factory() -> AsyncIterator:
        async with lock, maker() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    return factory


@pytest_asyncio.fixture
async def store() -> AsyncIterator[CallStateStore]:
    client = fake_aioredis.FakeRedis(decode_responses=True)
    yield CallStateStore(client)
    await client.flushall()
    await client.aclose()


@pytest.fixture
def hub() -> EventHub:
    return EventHub()


@pytest.fixture
def registry() -> SessionRegistry:
    return SessionRegistry()
