// Day-level analytics polling. The realtime store reduces the WebSocket event
// stream into *session* numbers; the day-level aggregates (total calls today,
// junk %, avg AI handle time) come from the backend's analytics endpoint, which
// we poll on an interval — the same cheap, stateless pattern as the health probe.

import { useEffect, useState } from "react";
import { fetchAnalytics } from "../lib/api";
import type { AnalyticsSummary } from "../types/analytics";

/** How often to refresh the day-level footer numbers. */
export const ANALYTICS_POLL_MS = 5000;

/**
 * Poll `GET /api/analytics/summary` and return the latest snapshot (null until
 * the first successful fetch). Failures are swallowed — the footer just keeps
 * showing the last good numbers, like a stale-but-live dashboard should.
 */
export function useDayAnalytics(
  intervalMs: number = ANALYTICS_POLL_MS,
): AnalyticsSummary | null {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = () => {
      fetchAnalytics()
        .then((s) => {
          if (!cancelled) setSummary(s);
        })
        .catch(() => {
          /* keep the last good snapshot on the screen */
        });
    };
    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return summary;
}
