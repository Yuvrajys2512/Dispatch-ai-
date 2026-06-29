// Presentation layer for Severity — badge emoji + color coding (spec §6).
//
// This is *display only*. The dashboard never re-decides severity client-side
// (release gate: contract parity); it renders whatever the backend emitted.

import type { RouteTarget, Severity } from "../types/events";
import { SEVERITY_RANK } from "../types/events";

export interface SeverityStyle {
  /** The badge glyph from spec §6 (🔴🟠🟡🟢⚪). */
  emoji: string;
  /** Human label. */
  label: Severity;
  /** Left accent / border color. */
  accent: string;
  /** Badge pill background + text. */
  badge: string;
  /** Subtle card tint. */
  tint: string;
}

export const SEVERITY_STYLES: Record<Severity, SeverityStyle> = {
  CRITICAL: {
    emoji: "🔴",
    label: "CRITICAL",
    accent: "border-l-red-500",
    badge: "bg-red-500/15 text-red-300 ring-1 ring-red-500/40",
    tint: "bg-red-950/30",
  },
  HIGH: {
    emoji: "🟠",
    label: "HIGH",
    accent: "border-l-orange-500",
    badge: "bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/40",
    tint: "bg-orange-950/20",
  },
  MEDIUM: {
    emoji: "🟡",
    label: "MEDIUM",
    accent: "border-l-yellow-500",
    badge: "bg-yellow-500/15 text-yellow-200 ring-1 ring-yellow-500/40",
    tint: "bg-yellow-950/10",
  },
  LOW: {
    emoji: "🟢",
    label: "LOW",
    accent: "border-l-emerald-500",
    badge: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40",
    tint: "bg-emerald-950/10",
  },
  JUNK: {
    emoji: "⚪",
    label: "JUNK",
    accent: "border-l-neutral-600",
    badge: "bg-neutral-700/40 text-neutral-400 ring-1 ring-neutral-600/40",
    tint: "bg-neutral-900/40",
  },
};

export function severityStyle(severity: Severity): SeverityStyle {
  return SEVERITY_STYLES[severity];
}

/** Compare for descending-urgency sort (CRITICAL first, JUNK last). */
export function compareSeverityDesc(a: Severity, b: Severity): number {
  return SEVERITY_RANK[b] - SEVERITY_RANK[a];
}

/** Routes that mean "no operator ever touches this" — shown as auto-resolved. */
export function isAutoResolved(target: RouteTarget | null): boolean {
  return target === "AUTO_RESOLVE";
}
