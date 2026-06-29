"""GET /api/analytics/summary — route wiring + typed payload (infra-free).

The route normally talks to PostgreSQL via ``session_scope``; here we point that
at an in-memory SQLite engine so the endpoint is exercised end-to-end (FastAPI
serialization + the response contract the frontend mirrors) with no Docker.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401  (register tables)
from app.db.base import Base
from app.db.caller_counter import BUCKET_TZ
from app.db.repositories import CallRepository
from app.domain.enums import CallState, IncidentType, RouteTarget, Severity
from app.domain.models import Call, IncidentCard, RouteDecision
from app.main import app


@pytest_asyncio.fixture
async def seeded_maker():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(BUCKET_TZ)
    async with maker() as s:
        repo = CallRepository(s)
        await repo.create(
            Call(
                phone="+91-1",
                state=CallState.RESOLVED,
                started_at=now - timedelta(minutes=5),
                ended_at=now,
                incident=IncidentCard(
                    incident_type=IncidentType.OTHER,
                    severity=Severity.JUNK,
                    confidence=0.9,
                ),
                route=RouteDecision(
                    target=RouteTarget.AUTO_RESOLVE,
                    severity=Severity.JUNK,
                    confidence=0.9,
                ),
            )
        )
        await s.commit()
    yield maker
    await engine.dispose()


def test_summary_endpoint_returns_typed_payload(monkeypatch, seeded_maker):
    @asynccontextmanager
    async def fake_scope():
        async with seeded_maker() as s:
            yield s

    monkeypatch.setattr("app.analytics.router.session_scope", fake_scope)

    with TestClient(app) as client:
        resp = client.get("/api/analytics/summary")

    assert resp.status_code == 200
    body = resp.json()
    # Contract the frontend mirrors key-for-key.
    assert set(body) == {
        "total_calls",
        "junk_calls",
        "junk_pct",
        "auto_resolved",
        "avg_ai_handle_seconds",
        "severity_distribution",
        "calls_per_hour",
        "window_start",
        "generated_at",
    }
    assert body["total_calls"] == 1
    assert body["junk_calls"] == 1
    assert body["junk_pct"] == 100.0
    assert body["auto_resolved"] == 1
    assert body["severity_distribution"]["JUNK"] == 1
