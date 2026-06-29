import { useState } from "react";
import type { CallView } from "../store/callStore";
import { takeOver } from "../store/socket";
import { severityStyle } from "../lib/severity";
import { formatConfidence, formatDuration, humanizeEnum } from "../lib/format";
import { SeverityBadge } from "./SeverityBadge";
import { Transcript } from "./Transcript";
import { IncidentPanel } from "./IncidentPanel";

interface Props {
  call: CallView;
  /** Current wall-clock in unix seconds, ticked by the parent for live duration. */
  now: number;
}

function liveDuration(call: CallView, now: number): number {
  if (call.durationSeconds !== null) return call.durationSeconds;
  return Math.max(0, now - call.startedTs);
}

export function CallCard({ call, now }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState(false);

  const style = severityStyle(call.severity);
  const card = call.incident;
  const isJunk = call.severity === "JUNK";
  const autoResolved =
    call.route?.target === "AUTO_RESOLVE" || (isJunk && call.ended);
  const summary =
    card?.summary ??
    (card ? humanizeEnum(card.incident_type) : null) ??
    "Triaging…";

  const onTakeOver = async () => {
    setPending(true);
    await takeOver(call.callId);
    // The card updates when `operator.takeover` / `call.ended` arrive over WS;
    // we don't optimistically mutate state here.
    setPending(false);
  };

  const stateLabel = call.takenOver
    ? "HANDED OVER — operator on the line"
    : call.ended
      ? humanizeEnum(call.state)
      : null;

  return (
    <article
      data-testid="call-card"
      data-call-id={call.callId}
      data-severity={call.severity}
      className={`border-l-4 ${style.accent} ${style.tint} ${
        call.ended ? "opacity-70" : ""
      } rounded-r border-y border-r border-neutral-800 transition-opacity`}
    >
      <div className="flex items-start justify-between gap-4 p-4">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-3">
            <SeverityBadge severity={call.severity} />
            <span className="font-mono text-sm text-neutral-300">
              {call.phone}
            </span>
            {call.hadGap && (
              <span
                title="Event gap detected on this call"
                className="text-xs text-amber-400"
              >
                ⚠ gap
              </span>
            )}
          </div>

          <p className="truncate text-base font-medium text-neutral-100">
            {summary}
          </p>

          {card?.location_text && (
            <p className="truncate text-sm text-neutral-400">
              📍 {card.location_text}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-neutral-500">
            {card && <span>🤖 AI confidence: {formatConfidence(card.confidence)}</span>}
            <span data-testid="duration">
              ⏱ {formatDuration(liveDuration(call, now))}
            </span>
            {call.scenario && (
              <span className="text-neutral-600">{call.scenario}</span>
            )}
          </div>

          {stateLabel && (
            <p
              data-testid="state-label"
              className={`text-xs font-semibold ${
                call.takenOver ? "text-sky-300" : "text-neutral-400"
              }`}
            >
              {stateLabel}
            </p>
          )}
        </div>

        <div className="flex flex-col items-end gap-2">
          {autoResolved ? (
            <span
              data-testid="auto-resolved"
              className="rounded bg-neutral-800 px-2 py-0.5 text-xs text-neutral-400"
            >
              Auto-resolved
            </span>
          ) : (
            <button
              type="button"
              onClick={onTakeOver}
              disabled={pending || call.takenOver || call.ended}
              className="rounded bg-red-600/90 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-neutral-700 disabled:text-neutral-400"
            >
              {call.takenOver
                ? "🎙 Handed over"
                : pending
                  ? "Connecting…"
                  : "🎙 TAKE OVER"}
            </button>
          )}

          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="rounded border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-800"
          >
            {autoResolved
              ? expanded
                ? "Hide"
                : "🔍 REVIEW"
              : expanded
                ? "Hide details"
                : "📄 VIEW TRANSCRIPT"}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="grid gap-4 border-t border-neutral-800 p-4 md:grid-cols-2">
          <IncidentPanel call={call} />
          <Transcript finals={call.finals} partial={call.partial} />
        </div>
      )}
    </article>
  );
}
