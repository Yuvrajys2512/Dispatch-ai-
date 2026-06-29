// Small display formatters shared across cards.

/** Seconds → "m:ss" (e.g. 42 → "0:42", 75 → "1:15"). */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(s / 60);
  const seconds = s % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** Confidence 0–1 → whole-percent string (e.g. 0.94 → "94%"). */
export function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

/** Title-case an enum value for display (e.g. "OPERATOR_IMMEDIATE" → "Operator immediate"). */
export function humanizeEnum(value: string): string {
  const lower = value.replace(/_/g, " ").toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}
