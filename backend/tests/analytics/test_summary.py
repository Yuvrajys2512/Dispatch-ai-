"""Analytics aggregation — correctness + reconciliation against the DB.

These seed a known spread of calls (today + yesterday, across severities and
routes) and assert the aggregates are exactly what a direct DB count returns for
the same IST-today window — the numbers must *reconcile*, not merely snapshot.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.analytics.queries import _ist_start_of_day, compute_summary
from app.db.caller_counter import BUCKET_TZ
from app.db.models import CallORM
from app.db.repositories import CallRepository
from app.domain.enums import CallState, IncidentType, RouteTarget, Severity
from app.domain.models import Call, IncidentCard, RouteDecision

# A fixed "now" inside the IST day so the test is deterministic.
_NOW = datetime(2026, 6, 24, 15, 0, tzinfo=BUCKET_TZ)
_TODAY_9AM = datetime(2026, 6, 24, 9, 0, tzinfo=BUCKET_TZ)
_TODAY_11AM = datetime(2026, 6, 24, 11, 0, tzinfo=BUCKET_TZ)
_YESTERDAY = datetime(2026, 6, 23, 20, 0, tzinfo=BUCKET_TZ)


def _call(
    *,
    phone: str,
    severity: Severity,
    target: RouteTarget,
    started_at: datetime,
    duration_s: float | None,
) -> Call:
    ended_at = started_at + timedelta(seconds=duration_s) if duration_s else None
    return Call(
        phone=phone,
        state=CallState.RESOLVED,
        started_at=started_at,
        ended_at=ended_at,
        incident=IncidentCard(
            incident_type=IncidentType.OTHER,
            severity=severity,
            confidence=0.9,
        ),
        route=RouteDecision(
            target=target, severity=severity, confidence=0.9, handoff=False
        ),
    )


async def _seed(session) -> None:
    repo = CallRepository(session)
    spread = [
        # 3 today, one of them JUNK auto-resolved (20s), one AI_RESOLVE (40s).
        _call(phone="+91-1", severity=Severity.CRITICAL, target=RouteTarget.OPERATOR_IMMEDIATE,
              started_at=_TODAY_9AM, duration_s=120),
        _call(phone="+91-2", severity=Severity.JUNK, target=RouteTarget.AUTO_RESOLVE,
              started_at=_TODAY_9AM, duration_s=20),
        _call(phone="+91-3", severity=Severity.LOW, target=RouteTarget.AI_RESOLVE,
              started_at=_TODAY_11AM, duration_s=40),
        # Yesterday — must be excluded from "today".
        _call(phone="+91-4", severity=Severity.JUNK, target=RouteTarget.AUTO_RESOLVE,
              started_at=_YESTERDAY, duration_s=15),
    ]
    for c in spread:
        await repo.create(c)
    await session.commit()


@pytest.mark.asyncio
async def test_totals_and_junk_pct_reconcile_with_db(session):
    await _seed(session)
    summary = await compute_summary(session, now=_NOW)

    start = _ist_start_of_day(_NOW)
    db_total = await session.scalar(
        select(func.count()).select_from(CallORM).where(CallORM.started_at >= start)
    )
    db_junk = await session.scalar(
        select(func.count())
        .select_from(CallORM)
        .where(CallORM.started_at >= start, CallORM.severity == Severity.JUNK)
    )

    assert summary.total_calls == db_total == 3  # yesterday excluded
    assert summary.junk_calls == db_junk == 1
    assert summary.junk_pct == round((db_junk / db_total) * 100, 1)
    assert summary.junk_pct == pytest.approx(33.3)


@pytest.mark.asyncio
async def test_avg_ai_handle_time_over_ai_resolved_only(session):
    await _seed(session)
    summary = await compute_summary(session, now=_NOW)
    # AI-resolved today = AUTO_RESOLVE (20s) + AI_RESOLVE (40s) → mean 30s.
    # The CRITICAL operator call (120s) is excluded.
    assert summary.avg_ai_handle_seconds == pytest.approx(30.0)
    assert summary.auto_resolved == 1


@pytest.mark.asyncio
async def test_severity_distribution_and_calls_per_hour(session):
    await _seed(session)
    summary = await compute_summary(session, now=_NOW)

    assert summary.severity_distribution[Severity.JUNK.value] == 1
    assert summary.severity_distribution[Severity.CRITICAL.value] == 1
    assert summary.severity_distribution[Severity.LOW.value] == 1
    assert summary.severity_distribution[Severity.HIGH.value] == 0
    # Every severity bucket is present (zero-filled), so the dashboard renders all.
    assert set(summary.severity_distribution) == {s.value for s in Severity}

    # Two calls at 09:00 IST, one at 11:00 IST.
    assert summary.calls_per_hour[9] == 2
    assert summary.calls_per_hour[11] == 1
    assert sum(summary.calls_per_hour.values()) == 3
    assert set(summary.calls_per_hour) == set(range(24))


@pytest.mark.asyncio
async def test_empty_db_is_all_zero(session):
    summary = await compute_summary(session, now=_NOW)
    assert summary.total_calls == 0
    assert summary.junk_pct == 0.0
    assert summary.avg_ai_handle_seconds == 0.0
    assert summary.auto_resolved == 0
