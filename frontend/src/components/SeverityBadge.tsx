import type { Severity } from "../types/events";
import { severityStyle } from "../lib/severity";

interface Props {
  severity: Severity;
  className?: string;
}

/** The emoji + color-coded severity pill from spec §6 (🔴🟠🟡🟢⚪). */
export function SeverityBadge({ severity, className = "" }: Props) {
  const style = severityStyle(severity);
  return (
    <span
      data-testid="severity-badge"
      data-severity={severity}
      className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-semibold tracking-wide ${style.badge} ${className}`}
    >
      <span aria-hidden>{style.emoji}</span>
      {style.label}
    </span>
  );
}
