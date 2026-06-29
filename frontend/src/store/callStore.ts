// The dashboard's single source of truth: a Zustand store that reduces the
// discriminated event union (`DispatchEvent`) into a map of live call views.
//
// The reducer (`applyEvent`) is deliberately pure of any I/O — it never touches
// a socket or `fetch`. The WebSocket lifecycle lives in `socket.ts`, which only
// *calls* these actions. That split is what lets the tests drive the whole store
// with synthetic events and zero infrastructure.

import { create } from "zustand";
import type {
  Call,
  CallState,
  DispatchEvent,
  IncidentCard,
  RouteTarget,
  Severity,
} from "../types/events";
import { isTerminal } from "../types/events";

export type ConnectionState = "connecting" | "online" | "offline";

export interface TranscriptLine {
  seq: number;
  speaker: "CALLER" | "AI" | "OPERATOR";
  text: string;
  confidence: number | null;
}

export interface RouteView {
  target: RouteTarget;
  severity: Severity;
  confidence: number;
  reason: string;
  handoff: boolean;
}

/** The live, denormalized view of one call the dashboard renders. */
export interface CallView {
  callId: string;
  phone: string;
  scenario: string | null;
  incident: IncidentCard | null;
  severity: Severity;
  route: RouteView | null;
  state: CallState;
  finals: TranscriptLine[];
  partial: string | null;
  /** Unix seconds when the call started (event ts or parsed `started_at`). */
  startedTs: number;
  endedTs: number | null;
  /** Authoritative duration once `call.ended` lands; else null (tick live). */
  durationSeconds: number | null;
  takenOver: boolean;
  ended: boolean;
  /** Last `seq` applied for this call; null until the first event is seen. */
  lastSeq: number | null;
  hadGap: boolean;
}

export interface SessionStats {
  totalStarted: number;
  endedCount: number;
  junkCount: number;
  autoResolvedCount: number;
}

interface CallStore {
  calls: Record<string, CallView>;
  connection: ConnectionState;
  /** Cumulative count of detected `seq` gaps this session (stream-health). */
  gaps: number;
  stats: SessionStats;

  applyEvent: (event: DispatchEvent) => void;
  hydrate: (calls: Call[]) => void;
  removeCall: (callId: string) => void;
  setConnection: (state: ConnectionState) => void;
  reset: () => void;
}

const DEFAULT_SEVERITY: Severity = "MEDIUM";

function newView(callId: string, startedTs: number): CallView {
  return {
    callId,
    phone: "—",
    scenario: null,
    incident: null,
    severity: DEFAULT_SEVERITY,
    route: null,
    state: "GREETING",
    finals: [],
    partial: null,
    startedTs,
    endedTs: null,
    durationSeconds: null,
    takenOver: false,
    ended: false,
    lastSeq: null,
    hadGap: false,
  };
}

/** Track `seq` continuity: a non-contiguous jump (after the first seen) is a gap. */
function nextSeqState(
  prev: number | null,
  seq: number,
): { lastSeq: number; gap: boolean } {
  const gap = prev !== null && seq !== prev + 1;
  return { lastSeq: seq, gap };
}

function viewFromCall(call: Call): CallView {
  const startedTs = Date.parse(call.started_at) / 1000;
  const endedTs = call.ended_at ? Date.parse(call.ended_at) / 1000 : null;
  return {
    callId: call.id,
    phone: call.phone,
    scenario: null,
    incident: call.incident,
    severity: call.incident.severity,
    route: call.route
      ? {
          target: call.route.target,
          severity: call.route.severity,
          confidence: call.route.confidence,
          reason: call.route.reason,
          handoff: call.route.handoff,
        }
      : null,
    state: call.state,
    finals: call.transcript
      .filter((t) => t.is_final)
      .map((t) => ({
        seq: t.seq,
        speaker: t.speaker,
        text: t.text,
        confidence: t.confidence,
      })),
    partial: null,
    startedTs: Number.isFinite(startedTs) ? startedTs : Date.now() / 1000,
    endedTs,
    durationSeconds: null,
    takenOver: call.state === "HANDED_OVER",
    ended: isTerminal(call.state),
    lastSeq: null,
    hadGap: false,
  };
}

export const useCallStore = create<CallStore>((set) => ({
  calls: {},
  connection: "connecting",
  gaps: 0,
  stats: { totalStarted: 0, endedCount: 0, junkCount: 0, autoResolvedCount: 0 },

  applyEvent: (event) =>
    set((store) => {
      const calls = { ...store.calls };
      const stats = { ...store.stats };
      let gaps = store.gaps;

      const existing = calls[event.call_id];
      const view: CallView = existing
        ? { ...existing }
        : newView(event.call_id, event.ts);

      const seqState = nextSeqState(view.lastSeq, event.seq);
      view.lastSeq = seqState.lastSeq;
      if (seqState.gap) {
        view.hadGap = true;
        gaps += 1;
      }

      switch (event.type) {
        case "call.started": {
          view.phone = event.phone;
          view.scenario = event.scenario;
          view.startedTs = event.ts;
          if (!existing) stats.totalStarted += 1;
          break;
        }
        case "transcript.partial": {
          view.partial = event.text;
          break;
        }
        case "transcript.final": {
          // De-dupe by turn_seq so a replayed final replaces, not duplicates.
          const finals = view.finals.filter((f) => f.seq !== event.turn_seq);
          finals.push({
            seq: event.turn_seq,
            speaker: "CALLER",
            text: event.text,
            confidence: event.confidence,
          });
          finals.sort((a, b) => a.seq - b.seq);
          view.finals = finals;
          view.partial = null;
          break;
        }
        case "incident.updated": {
          view.incident = event.incident;
          view.severity = event.incident.severity;
          break;
        }
        case "severity.changed": {
          view.severity = event.current;
          break;
        }
        case "route.decided": {
          view.route = {
            target: event.target,
            severity: event.severity,
            confidence: event.confidence,
            reason: event.reason,
            handoff: event.handoff,
          };
          view.severity = event.severity;
          break;
        }
        case "operator.takeover": {
          view.takenOver = true;
          view.state = "HANDED_OVER";
          break;
        }
        case "call.ended": {
          view.ended = true;
          view.state = event.final_state;
          view.endedTs = event.ts;
          view.durationSeconds = event.duration_seconds;
          view.partial = null;
          stats.endedCount += 1;
          if (view.severity === "JUNK") stats.junkCount += 1;
          if (view.route?.target === "AUTO_RESOLVE") {
            stats.autoResolvedCount += 1;
          }
          break;
        }
      }

      calls[event.call_id] = view;
      return { calls, stats, gaps };
    }),

  hydrate: (incoming) =>
    set((store) => {
      const calls = { ...store.calls };
      for (const call of incoming) {
        // Don't clobber a call we're already tracking from the live stream.
        if (!calls[call.id]) calls[call.id] = viewFromCall(call);
      }
      return { calls };
    }),

  removeCall: (callId) =>
    set((store) => {
      if (!store.calls[callId]) return store;
      const calls = { ...store.calls };
      delete calls[callId];
      return { calls };
    }),

  setConnection: (connection) => set({ connection }),

  reset: () =>
    set({
      calls: {},
      connection: "connecting",
      gaps: 0,
      stats: {
        totalStarted: 0,
        endedCount: 0,
        junkCount: 0,
        autoResolvedCount: 0,
      },
    }),
}));
