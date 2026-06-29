// Hand-written TypeScript mirror of the backend realtime contract.
//
// The source of truth is the Python side — keep these in lockstep:
//   * enums          → backend/app/domain/enums.py
//   * IncidentCard   → backend/app/domain/models.py
//   * the 8 events   → backend/app/realtime/events.py  (discriminated on `type`)
//
// A drift here is a silent bug: the store reduces this union by its `type` tag,
// so every literal below must match a Pydantic `Literal[...]` exactly.

// --- enums (string-valued, identical to the Python `str, Enum` members) ----

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "JUNK";

export type CallState =
  | "GREETING"
  | "INCIDENT_TYPE"
  | "LOCATION"
  | "DETAILS"
  | "SEVERITY_SCORE"
  | "ROUTE"
  // terminal
  | "ROUTED"
  | "HANDED_OVER"
  | "RESOLVED"
  | "ABANDONED";

export type IncidentType =
  | "ACCIDENT"
  | "ASSAULT"
  | "THEFT"
  | "FIRE"
  | "MEDICAL"
  | "DOMESTIC"
  | "OTHER"
  | "UNKNOWN";

export type RouteTarget =
  | "OPERATOR_IMMEDIATE"
  | "OPERATOR_QUEUE"
  | "AI_RESOLVE"
  | "AUTO_RESOLVE";

export type Speaker = "CALLER" | "AI" | "OPERATOR";

// --- domain models embedded in events / the hydration endpoint -------------

export interface GeoPoint {
  lat: number;
  lng: number;
}

/** Mirrors `app.domain.models.IncidentCard` — the progressively-filled card. */
export interface IncidentCard {
  caller_name: string | null;
  location_text: string | null;
  location_geo: GeoPoint | null;
  incident_type: IncidentType;
  people_involved: number | null;
  severity: Severity;
  confidence: number;
  needs_ambulance: boolean;
  needs_police: boolean;
  needs_fire: boolean;
  summary: string | null;
  details: Record<string, unknown>;
}

/** Mirrors `app.domain.models.TranscriptTurn`. */
export interface TranscriptTurn {
  id: string;
  seq: number;
  speaker: Speaker;
  text: string;
  is_final: boolean;
  confidence: number | null;
  created_at: string;
}

/** Mirrors `app.domain.models.RouteDecision`. */
export interface RouteDecision {
  target: RouteTarget;
  severity: Severity;
  confidence: number;
  reason: string;
  handoff: boolean;
  decided_at: string;
}

/** Mirrors `app.domain.models.Call` — the shape returned by `/api/calls/live`. */
export interface Call {
  id: string;
  caller_id: string | null;
  phone: string;
  state: CallState;
  incident: IncidentCard;
  route: RouteDecision | null;
  transcript: TranscriptTurn[];
  started_at: string;
  ended_at: string | null;
}

// --- the 8 events (discriminated union on `type`) --------------------------

interface BaseEvent {
  call_id: string;
  seq: number;
  ts: number;
}

export interface CallStartedEvent extends BaseEvent {
  type: "call.started";
  phone: string;
  scenario: string | null;
}

export interface TranscriptPartialEvent extends BaseEvent {
  type: "transcript.partial";
  text: string;
  confidence: number;
}

export interface TranscriptFinalEvent extends BaseEvent {
  type: "transcript.final";
  text: string;
  confidence: number;
  turn_seq: number;
}

export interface IncidentUpdatedEvent extends BaseEvent {
  type: "incident.updated";
  incident: IncidentCard;
}

export interface SeverityChangedEvent extends BaseEvent {
  type: "severity.changed";
  previous: Severity | null;
  current: Severity;
}

export interface RouteDecidedEvent extends BaseEvent {
  type: "route.decided";
  target: RouteTarget;
  severity: Severity;
  confidence: number;
  reason: string;
  handoff: boolean;
}

export interface CallEndedEvent extends BaseEvent {
  type: "call.ended";
  final_state: CallState;
  duration_seconds: number;
}

export interface OperatorTakeoverEvent extends BaseEvent {
  type: "operator.takeover";
  reason: string;
}

export type DispatchEvent =
  | CallStartedEvent
  | TranscriptPartialEvent
  | TranscriptFinalEvent
  | IncidentUpdatedEvent
  | SeverityChangedEvent
  | RouteDecidedEvent
  | CallEndedEvent
  | OperatorTakeoverEvent;

export type EventType = DispatchEvent["type"];

// --- terminal-state + severity helpers (mirror enums.py semantics) ---------

export const TERMINAL_STATES: ReadonlySet<CallState> = new Set<CallState>([
  "ROUTED",
  "HANDED_OVER",
  "RESOLVED",
  "ABANDONED",
]);

export function isTerminal(state: CallState): boolean {
  return TERMINAL_STATES.has(state);
}

/** Numeric urgency, CRITICAL=4 … JUNK=0 (mirrors `Severity.rank`). */
export const SEVERITY_RANK: Record<Severity, number> = {
  CRITICAL: 4,
  HIGH: 3,
  MEDIUM: 2,
  LOW: 1,
  JUNK: 0,
};
