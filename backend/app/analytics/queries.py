"""Day-level ops analytics over the persisted calls (Phase 6).

These aggregate the durable ``calls`` rows into the numbers the dispatcher
dashboard's footer shows (spec §6): total calls today, junk %, average AI handle
time, the severity mix, and a calls-per-hour histogram.

**The window is "today" in IST** — the same Indian-calendar day the repeat-caller
counter buckets on (:mod:`app.db.caller_counter`) — so "calls today" means one
thing across the whole system. We compute the IST start-of-day, convert it to UTC
(rows store timezone-aware UTC timestamps), and aggregate everything from there.

The numbers are designed to **reconcile**: ``total_calls`` is exactly
``SELECT COUNT(*) FROM calls WHERE started_at >= <IST start of day>`` and
``junk_calls`` the same with ``severity = 'JUNK'`` — the tests assert that
equality rather than snapshotting a value. To stay portable across PostgreSQL and
the SQLite test backend we pull the relevant columns for the day in one query and
fold the histogram/averages in Python (no dialect-specific date functions).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.caller_counter import BUCKET_TZ
from app.db.models import CallORM
from app.domain.enums import RouteTarget, Severity

# Routes the AI closes on its own (no operator handled the call) — "AI handle
# time" is measured over these.
_AI_RESOLVED_ROUTES = frozenset({RouteTarget.AI_RESOLVE, RouteTarget.AUTO_RESOLVE})


def _ist_start_of_day(now: datetime | None = None) -> datetime:
    """The most recent IST midnight, as a timezone-aware datetime."""
    now_ist = (now or datetime.now(BUCKET_TZ)).astimezone(BUCKET_TZ)
    return now_ist.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class AnalyticsSummary:
    """The day's ops numbers (all over the IST-today window)."""

    total_calls: int
    junk_calls: int
    junk_pct: float  # 0–100, one decimal
    auto_resolved: int
    avg_ai_handle_seconds: float  # avg duration over AI-resolved calls
    severity_distribution: dict[str, int]  # Severity value → count
    calls_per_hour: dict[int, int]  # IST hour 0–23 → count
    window_start: datetime
    generated_at: datetime = field(default_factory=lambda: datetime.now(BUCKET_TZ))


async def compute_summary(
    session: AsyncSession, *, now: datetime | None = None
) -> AnalyticsSummary:
    """Aggregate today's calls into an :class:`AnalyticsSummary`."""
    start = _ist_start_of_day(now)

    rows = (
        await session.execute(
            select(
                CallORM.severity,
                CallORM.route_target,
                CallORM.started_at,
                CallORM.ended_at,
            ).where(CallORM.started_at >= start)
        )
    ).all()

    total = len(rows)
    junk = sum(1 for r in rows if r.severity is Severity.JUNK)
    auto_resolved = sum(
        1 for r in rows if r.route_target is RouteTarget.AUTO_RESOLVE
    )

    severity_distribution = {s.value: 0 for s in Severity}
    for r in rows:
        severity_distribution[r.severity.value] += 1

    # Calls-per-hour histogram, bucketed by the call's start hour in IST.
    calls_per_hour = {h: 0 for h in range(24)}
    for r in rows:
        hour = r.started_at.astimezone(BUCKET_TZ).hour
        calls_per_hour[hour] += 1

    # Average handle time over AI-resolved, completed calls.
    handle_times = [
        (r.ended_at - r.started_at).total_seconds()
        for r in rows
        if r.route_target in _AI_RESOLVED_ROUTES and r.ended_at is not None
    ]
    avg_ai = round(sum(handle_times) / len(handle_times), 2) if handle_times else 0.0

    junk_pct = round((junk / total) * 100, 1) if total else 0.0

    return AnalyticsSummary(
        total_calls=total,
        junk_calls=junk,
        junk_pct=junk_pct,
        auto_resolved=auto_resolved,
        avg_ai_handle_seconds=avg_ai,
        severity_distribution=severity_distribution,
        calls_per_hour=calls_per_hour,
        window_start=start,
    )
