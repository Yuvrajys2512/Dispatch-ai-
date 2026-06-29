import { beforeEach, describe, expect, it } from "vitest";
import { useCallStore } from "./callStore";
import { analytics, sortedCalls } from "./selectors";
import type {
  Call,
  DispatchEvent,
  IncidentCard,
  Severity,
} from "../types/events";

// --- synthetic-event builders (mirror the backend emit order) --------------

function card(over: Partial<IncidentCard> = {}): IncidentCard {
  return {
    caller_name: null,
    location_text: null,
    location_geo: null,
    incident_type: "UNKNOWN",
    people_involved: null,
    severity: "MEDIUM",
    confidence: 0,
    needs_ambulance: false,
    needs_police: false,
    needs_fire: false,
    summary: null,
    details: {},
    ...over,
  };
}

// Distributive Omit so the union's per-variant fields survive (a plain
// Omit<union, K> collapses to the keys common to every member).
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;
type EventInput = DistributiveOmit<DispatchEvent, "call_id" | "seq" | "ts">;

/** Build the ordered event stream of one accident call, like the simulator emits. */
function accidentStream(callId = "call-1"): DispatchEvent[] {
  let seq = 0;
  const e = (ev: EventInput): DispatchEvent =>
    ({ ...ev, call_id: callId, seq: seq++, ts: 1000 + seq }) as DispatchEvent;
  return [
    e({ type: "call.started", phone: "+91-98100-00001", scenario: "accident" }),
    e({ type: "transcript.partial", text: "Accident ho gaya", confidence: 0.7 }),
    e({
      type: "transcript.final",
      text: "Accident ho gaya, do log ghayal hain",
      confidence: 0.91,
      turn_seq: 0,
    }),
    e({
      type: "incident.updated",
      incident: card({
        incident_type: "ACCIDENT",
        severity: "CRITICAL",
        confidence: 0.92,
        people_involved: 2,
        needs_ambulance: true,
        summary: "Road accident, 2 injured",
      }),
    }),
    e({ type: "severity.changed", previous: "MEDIUM", current: "CRITICAL" }),
    e({
      type: "transcript.final",
      text: "NH-24 par, Ghaziabad toll plaza ke paas",
      confidence: 0.88,
      turn_seq: 1,
    }),
    e({
      type: "incident.updated",
      incident: card({
        incident_type: "ACCIDENT",
        severity: "CRITICAL",
        confidence: 0.91,
        people_involved: 2,
        needs_ambulance: true,
        location_text: "NH-24, Ghaziabad toll plaza",
        location_geo: { lat: 28.66, lng: 77.45 },
        summary: "Road accident, 2 injured",
      }),
    }),
    e({
      type: "route.decided",
      target: "OPERATOR_IMMEDIATE",
      severity: "CRITICAL",
      confidence: 0.91,
      reason: "CRITICAL: instant handoff (severity >= HIGH)",
      handoff: true,
    }),
    e({ type: "call.ended", final_state: "ROUTED", duration_seconds: 1.45 }),
  ];
}

function feed(events: DispatchEvent[]): void {
  const { applyEvent } = useCallStore.getState();
  for (const ev of events) applyEvent(ev);
}

beforeEach(() => useCallStore.getState().reset());

describe("call store reducer", () => {
  it("folds a full accident stream into a complete call view", () => {
    feed(accidentStream());
    const call = useCallStore.getState().calls["call-1"];

    expect(call.phone).toBe("+91-98100-00001");
    expect(call.scenario).toBe("accident");
    expect(call.severity).toBe("CRITICAL");
    expect(call.incident?.location_text).toBe("NH-24, Ghaziabad toll plaza");
    expect(call.incident?.people_involved).toBe(2);
    expect(call.route?.target).toBe("OPERATOR_IMMEDIATE");
    expect(call.route?.handoff).toBe(true);
    expect(call.ended).toBe(true);
    expect(call.state).toBe("ROUTED");
    expect(call.durationSeconds).toBe(1.45);
    expect(call.hadGap).toBe(false);
  });

  it("fills the card progressively (location absent then present)", () => {
    const events = accidentStream();
    const upToFirstIncident = events.slice(0, 4); // through the first incident.updated
    feed(upToFirstIncident);
    expect(
      useCallStore.getState().calls["call-1"].incident?.location_text,
    ).toBeNull();

    feed(events.slice(4));
    expect(
      useCallStore.getState().calls["call-1"].incident?.location_text,
    ).toBe("NH-24, Ghaziabad toll plaza");
  });

  it("appends finals in turn order and clears the partial on final", () => {
    feed(accidentStream());
    const call = useCallStore.getState().calls["call-1"];
    expect(call.finals.map((f) => f.seq)).toEqual([0, 1]);
    expect(call.finals[0].text).toContain("Accident ho gaya");
    expect(call.partial).toBeNull();
  });

  it("de-dupes a replayed final by turn_seq", () => {
    feed([
      {
        type: "call.started",
        call_id: "c",
        seq: 0,
        ts: 1,
        phone: "+91",
        scenario: null,
      },
      {
        type: "transcript.final",
        call_id: "c",
        seq: 1,
        ts: 2,
        text: "first",
        confidence: 0.9,
        turn_seq: 0,
      },
      {
        type: "transcript.final",
        call_id: "c",
        seq: 2,
        ts: 3,
        text: "first (corrected)",
        confidence: 0.95,
        turn_seq: 0,
      },
    ]);
    const call = useCallStore.getState().calls["c"];
    expect(call.finals).toHaveLength(1);
    expect(call.finals[0].text).toBe("first (corrected)");
  });

  it("detects a seq gap and counts it", () => {
    feed([
      { type: "call.started", call_id: "c", seq: 0, ts: 1, phone: "+91", scenario: null },
      { type: "severity.changed", call_id: "c", seq: 1, ts: 2, previous: null, current: "HIGH" },
      // seq jumps 1 -> 3 (a dropped event)
      { type: "severity.changed", call_id: "c", seq: 3, ts: 3, previous: "HIGH", current: "CRITICAL" },
    ]);
    expect(useCallStore.getState().calls["c"].hadGap).toBe(true);
    expect(useCallStore.getState().gaps).toBe(1);
  });

  it("reflects a takeover as HANDED_OVER without ending the call", () => {
    feed([
      { type: "call.started", call_id: "c", seq: 0, ts: 1, phone: "+91", scenario: null },
      { type: "operator.takeover", call_id: "c", seq: 1, ts: 2, reason: "manual" },
    ]);
    const call = useCallStore.getState().calls["c"];
    expect(call.takenOver).toBe(true);
    expect(call.state).toBe("HANDED_OVER");
    expect(call.ended).toBe(false);
  });

  it("removes a call on demand (linger cleanup)", () => {
    feed(accidentStream());
    expect(useCallStore.getState().calls["call-1"]).toBeDefined();
    useCallStore.getState().removeCall("call-1");
    expect(useCallStore.getState().calls["call-1"]).toBeUndefined();
  });

  it("creates a stub view for an out-of-order event before call.started", () => {
    feed([
      {
        type: "incident.updated",
        call_id: "late",
        seq: 5,
        ts: 9,
        incident: card({ severity: "HIGH" }),
      },
    ]);
    const call = useCallStore.getState().calls["late"];
    expect(call).toBeDefined();
    expect(call.severity).toBe("HIGH");
    expect(call.hadGap).toBe(false); // first event seen for this call
  });
});

describe("hydration", () => {
  function hydrationCall(over: Partial<Call> = {}): Call {
    return {
      id: "h1",
      caller_id: null,
      phone: "+91-70000-00002",
      state: "LOCATION",
      incident: card({ severity: "MEDIUM", incident_type: "THEFT" }),
      route: null,
      transcript: [
        {
          id: "t0",
          seq: 0,
          speaker: "CALLER",
          text: "chori ho gayi",
          is_final: true,
          confidence: 0.9,
          created_at: "2026-06-24T10:00:00Z",
        },
      ],
      started_at: "2026-06-24T10:00:00Z",
      ended_at: null,
      ...over,
    };
  }

  it("adds snapshot calls and maps their transcript + severity", () => {
    useCallStore.getState().hydrate([hydrationCall()]);
    const call = useCallStore.getState().calls["h1"];
    expect(call.phone).toBe("+91-70000-00002");
    expect(call.severity).toBe("MEDIUM");
    expect(call.finals[0].text).toBe("chori ho gayi");
    expect(call.ended).toBe(false);
  });

  it("does not clobber a call already tracked from the live stream", () => {
    feed([
      { type: "call.started", call_id: "h1", seq: 0, ts: 1, phone: "LIVE", scenario: "x" },
    ]);
    useCallStore.getState().hydrate([hydrationCall()]);
    expect(useCallStore.getState().calls["h1"].phone).toBe("LIVE");
  });
});

describe("selectors", () => {
  function startedCall(id: string, severity: Severity, ts: number): DispatchEvent[] {
    return [
      { type: "call.started", call_id: id, seq: 0, ts, phone: id, scenario: null },
      {
        type: "incident.updated",
        call_id: id,
        seq: 1,
        ts: ts + 1,
        incident: card({ severity }),
      },
    ];
  }

  it("sorts calls by descending severity (CRITICAL → JUNK)", () => {
    feed(startedCall("low", "LOW", 10));
    feed(startedCall("crit", "CRITICAL", 20));
    feed(startedCall("med", "MEDIUM", 30));
    feed(startedCall("junk", "JUNK", 40));
    const order = sortedCalls(useCallStore.getState().calls).map((c) => c.callId);
    expect(order).toEqual(["crit", "med", "low", "junk"]);
  });

  it("derives session analytics including junk percentage", () => {
    feed(startedCall("a", "CRITICAL", 1));
    feed(startedCall("b", "JUNK", 2));
    // End the junk call so it counts toward junkCount.
    useCallStore.getState().applyEvent({
      type: "call.ended",
      call_id: "b",
      seq: 2,
      ts: 5,
      final_state: "RESOLVED",
      duration_seconds: 8,
    });
    const stats = analytics(useCallStore.getState());
    expect(stats.totalStarted).toBe(2);
    expect(stats.live).toBe(1);
    expect(stats.ended).toBe(1);
    expect(stats.junk).toBe(1);
    expect(stats.junkPct).toBe(50);
  });
});
