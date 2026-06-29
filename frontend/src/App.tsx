import { useEffect, useState } from "react";
import { useCallStore } from "./store/callStore";
import { useDashboardConnection } from "./store/socket";
import { analytics, sortedCalls } from "./store/selectors";
import { useDayAnalytics } from "./store/analytics";
import { CallCard } from "./components/CallCard";
import { AnalyticsBar } from "./components/AnalyticsBar";

const CONNECTION_DOT: Record<string, string> = {
  online: "bg-emerald-400",
  offline: "bg-red-500",
  connecting: "bg-amber-400",
};

const CONNECTION_LABEL: Record<string, string> = {
  online: "live",
  offline: "offline — reconnecting…",
  connecting: "connecting…",
};

/** A 1s wall-clock tick so live call durations count up. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function App() {
  useDashboardConnection();
  const now = useNow();
  const dayAnalytics = useDayAnalytics();

  const calls = useCallStore((s) => s.calls);
  const connection = useCallStore((s) => s.connection);
  const stats = useCallStore((s) => s.stats);
  const gaps = useCallStore((s) => s.gaps);

  const ordered = sortedCalls(calls);
  const derived = analytics({ calls, stats });

  return (
    <div className="flex min-h-screen flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between border-b border-neutral-800 px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold tracking-tight">DISPATCH AI</span>
          <span className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400">
            CONTROL ROOM
          </span>
          <span
            data-testid="live-count"
            className="rounded bg-neutral-800 px-2 py-0.5 text-xs font-semibold text-neutral-200"
          >
            {derived.live} live
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm">
          {gaps > 0 && (
            <span
              title="The dashboard detected a gap in the event stream"
              className="mr-2 text-xs text-amber-400"
            >
              ⚠ {gaps} stream gap{gaps === 1 ? "" : "s"}
            </span>
          )}
          <span
            data-testid="connection-dot"
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              CONNECTION_DOT[connection] ?? "bg-neutral-500"
            }`}
          />
          <span className="text-neutral-400">{CONNECTION_LABEL[connection]}</span>
        </div>
      </header>

      <main className="flex-1 px-6 py-5">
        {ordered.length === 0 ? (
          <div
            data-testid="empty-state"
            className="flex min-h-[50vh] flex-col items-center justify-center gap-2 text-center"
          >
            <p className="text-lg text-neutral-300">
              {connection === "offline"
                ? "Backend offline"
                : "No active calls"}
            </p>
            <p className="max-w-md text-sm text-neutral-500">
              {connection === "offline"
                ? "Lost the event stream. Retrying with backoff — cards return automatically."
                : "Waiting for incoming calls. Run the simulator to see the control room light up."}
            </p>
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-3">
            {ordered.map((call) => (
              <CallCard key={call.callId} call={call} now={now} />
            ))}
          </div>
        )}
      </main>

      <AnalyticsBar stats={derived} day={dayAnalytics} />
    </div>
  );
}
