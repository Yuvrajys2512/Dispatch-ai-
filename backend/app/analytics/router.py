"""Analytics API — the dashboard's day-level numbers (Phase 6, spec §6).

``GET /api/analytics/summary`` returns a single, typed snapshot the dashboard
polls like ``/health``. The response model is mirrored key-for-key by the
frontend (``frontend/src/types/analytics.ts``) so a drift is caught at the type
boundary, exactly like the realtime event contract.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.analytics.queries import AnalyticsSummary, compute_summary
from app.auth import RequireKey
from app.db.session import session_scope

router = APIRouter(prefix="/api/analytics", tags=["analytics"], dependencies=[RequireKey])


class AnalyticsResponse(BaseModel):
    """The day's ops numbers (IST-today window)."""

    total_calls: int
    junk_calls: int
    junk_pct: float
    auto_resolved: int
    avg_ai_handle_seconds: float
    severity_distribution: dict[str, int]
    calls_per_hour: dict[int, int]
    window_start: datetime
    generated_at: datetime

    @classmethod
    def from_summary(cls, s: AnalyticsSummary) -> AnalyticsResponse:
        return cls(
            total_calls=s.total_calls,
            junk_calls=s.junk_calls,
            junk_pct=s.junk_pct,
            auto_resolved=s.auto_resolved,
            avg_ai_handle_seconds=s.avg_ai_handle_seconds,
            severity_distribution=s.severity_distribution,
            calls_per_hour=s.calls_per_hour,
            window_start=s.window_start,
            generated_at=s.generated_at,
        )


@router.get("/summary", response_model=AnalyticsResponse)
async def analytics_summary() -> AnalyticsResponse:
    """Aggregate today's calls into the dashboard footer numbers."""
    async with session_scope() as s:
        summary = await compute_summary(s)
    return AnalyticsResponse.from_summary(summary)
