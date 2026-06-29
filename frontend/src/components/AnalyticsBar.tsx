import type { AnalyticsSummary } from "../types/analytics";
import type { Analytics } from "../store/selectors";

interface Props {
  /** Session numbers derived from the live event stream. */
  stats: Analytics;
  /** Day-level aggregates polled from the backend (null until first fetch). */
  day: AnalyticsSummary | null;
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-semibold text-neutral-200">{value}</span>
      <span className="text-neutral-500">{label}</span>
    </span>
  );
}

/** Average AI handle time in a compact `Xs` / `Xm Ys` form. */
function formatHandleTime(seconds: number): string {
  if (seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/**
 * Footer analytics bar (spec §6). Two rows of truth: the real **day-level**
 * aggregates from the backend (`TODAY: N calls │ X% junk │ avg AI time …`), and
 * the live **session** counters derived from the event stream. The day numbers
 * reconcile against the DB; the session numbers move as cards land.
 */
export function AnalyticsBar({ stats, day }: Props) {
  return (
    <footer
      data-testid="analytics-bar"
      className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-neutral-800 bg-neutral-950 px-6 py-3 text-xs"
    >
      <span className="text-neutral-400">📊 TODAY</span>
      {day ? (
        <>
          <Stat label="calls" value={day.total_calls} />
          <Stat label="junk" value={`${day.junk_pct}%`} />
          <Stat label="auto-resolved" value={day.auto_resolved} />
          <Stat
            label="avg AI time"
            value={formatHandleTime(day.avg_ai_handle_seconds)}
          />
        </>
      ) : (
        <span className="text-neutral-600" data-testid="analytics-loading">
          loading day-level numbers…
        </span>
      )}

      <span className="mx-1 text-neutral-700">│</span>
      <span className="text-neutral-400">SESSION</span>
      <Stat label="live" value={stats.live} />
      <Stat label="started" value={stats.totalStarted} />
      <Stat label="resolved" value={stats.ended} />
    </footer>
  );
}
