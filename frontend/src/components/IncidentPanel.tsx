import type { CallView } from "../store/callStore";
import { formatConfidence, humanizeEnum } from "../lib/format";
import { SeverityBadge } from "./SeverityBadge";

interface Props {
  call: CallView;
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
        {label}
      </span>
      <span className="text-sm text-neutral-200">{value}</span>
    </div>
  );
}

const dash = <span className="text-neutral-600">—</span>;

function needsList(card: NonNullable<CallView["incident"]>): React.ReactNode {
  const needs = [
    card.needs_ambulance && "🚑 Ambulance",
    card.needs_police && "🚓 Police",
    card.needs_fire && "🚒 Fire",
  ].filter(Boolean) as string[];
  return needs.length ? needs.join("  ·  ") : dash;
}

/**
 * The pre-filled incident form (spec §6 "expanded card"): the structured fields
 * the agent extracted, a caller-history placeholder (real data lands in Phase 6),
 * and a map-pin placeholder for any resolved `location_geo`.
 */
export function IncidentPanel({ call }: Props) {
  const card = call.incident;
  return (
    <div data-testid="incident-panel" className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Caller name" value={card?.caller_name ?? dash} />
        <Field
          label="Incident type"
          value={card ? humanizeEnum(card.incident_type) : dash}
        />
        <Field
          label="Location"
          value={card?.location_text ?? dash}
        />
        <Field
          label="People involved"
          value={card?.people_involved ?? dash}
        />
        <Field
          label="Severity"
          value={<SeverityBadge severity={call.severity} />}
        />
        <Field
          label="AI confidence"
          value={card ? formatConfidence(card.confidence) : dash}
        />
        <Field
          label="Units needed"
          value={card ? needsList(card) : dash}
        />
        <Field
          label="Caller history"
          value={
            <span className="text-neutral-500">No prior calls today</span>
          }
        />
      </div>

      {card?.summary && (
        <Field label="Summary" value={card.summary} />
      )}

      <div
        data-testid="map-placeholder"
        className="flex h-24 items-center justify-center rounded border border-dashed border-neutral-700 bg-neutral-950/60 text-xs text-neutral-500"
      >
        {card?.location_geo
          ? `📍 ${card.location_geo.lat.toFixed(4)}, ${card.location_geo.lng.toFixed(4)} — map pin (Phase 8)`
          : "📍 No coordinates resolved yet"}
      </div>
    </div>
  );
}
