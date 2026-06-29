// Derived views over the store: severity-sorted call list + session analytics.
// Pure functions of state so components and tests share one implementation.

import { compareSeverityDesc } from "../lib/severity";
import type { CallView } from "./callStore";

/**
 * Calls in operator-priority order: most urgent first (CRITICAL → JUNK), live
 * calls ahead of just-ended ones at the same severity, older calls first as the
 * final tie-break so a steady queue doesn't reshuffle.
 */
export function sortedCalls(calls: Record<string, CallView>): CallView[] {
  return Object.values(calls).sort((a, b) => {
    const bySeverity = compareSeverityDesc(a.severity, b.severity);
    if (bySeverity !== 0) return bySeverity;
    if (a.ended !== b.ended) return a.ended ? 1 : -1;
    return a.startedTs - b.startedTs;
  });
}

export interface Analytics {
  /** Calls currently in flight (not yet ended). */
  live: number;
  /** Calls started this session (live + ended). */
  totalStarted: number;
  /** Calls ended this session. */
  ended: number;
  /** Junk calls this session. */
  junk: number;
  /** Auto-resolved (AUTO_RESOLVE) calls this session. */
  autoResolved: number;
  /** Junk share of started calls, 0–100 (0 when nothing started yet). */
  junkPct: number;
}

export function analytics(state: {
  calls: Record<string, CallView>;
  stats: {
    totalStarted: number;
    endedCount: number;
    junkCount: number;
    autoResolvedCount: number;
  };
}): Analytics {
  const live = Object.values(state.calls).filter((c) => !c.ended).length;
  const { totalStarted, endedCount, junkCount, autoResolvedCount } =
    state.stats;
  const junkPct =
    totalStarted > 0 ? Math.round((junkCount / totalStarted) * 100) : 0;
  return {
    live,
    totalStarted,
    ended: endedCount,
    junk: junkCount,
    autoResolved: autoResolvedCount,
    junkPct,
  };
}
