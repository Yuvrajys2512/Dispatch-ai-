// Hand-written TypeScript mirror of the analytics API contract.
//
// Source of truth: backend/app/analytics/router.py (`AnalyticsResponse`).
// Keep these in lockstep — a drift here is a silent bug, exactly like the
// realtime event contract in `types/events.ts`.

import type { Severity } from "./events";

/** Mirrors `AnalyticsResponse` from `GET /api/analytics/summary` (IST-today). */
export interface AnalyticsSummary {
  total_calls: number;
  junk_calls: number;
  /** Junk share of today's calls, 0–100 (one decimal). */
  junk_pct: number;
  auto_resolved: number;
  /** Average AI handle time (seconds) over AI-resolved calls. */
  avg_ai_handle_seconds: number;
  /** Severity value → count (every Severity key present, zero-filled). */
  severity_distribution: Record<Severity, number>;
  /** IST hour 0–23 → calls started that hour. */
  calls_per_hour: Record<number, number>;
  /** ISO timestamp: IST start-of-day the window covers. */
  window_start: string;
  /** ISO timestamp: when the snapshot was computed. */
  generated_at: string;
}
