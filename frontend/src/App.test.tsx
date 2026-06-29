import { beforeEach, describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import App from "./App";
import { useCallStore } from "./store/callStore";
import type { DispatchEvent, IncidentCard } from "./types/events";

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

function emit(events: DispatchEvent[]) {
  act(() => {
    for (const ev of events) useCallStore.getState().applyEvent(ev);
  });
}

beforeEach(() => {
  useCallStore.getState().reset();
  // App opens the connection on mount; mark it online so we see the live UI,
  // not the offline banner. (The FakeWebSocket from setup keeps mount inert.)
  act(() => useCallStore.getState().setConnection("online"));
});

describe("App control room", () => {
  it("renders the empty state with a 0-live count when idle", () => {
    render(<App />);
    expect(screen.getByTestId("empty-state")).toBeTruthy();
    expect(screen.getByTestId("live-count").textContent).toContain("0 live");
    expect(screen.getByTestId("analytics-bar")).toBeTruthy();
  });

  it("renders a live call card and updates the live count off the store", () => {
    render(<App />);
    emit([
      {
        type: "call.started",
        call_id: "c1",
        seq: 0,
        ts: 1000,
        phone: "+91-98100-00001",
        scenario: "accident",
      },
      {
        type: "incident.updated",
        call_id: "c1",
        seq: 1,
        ts: 1001,
        incident: card({
          incident_type: "ACCIDENT",
          severity: "CRITICAL",
          confidence: 0.92,
          summary: "Accident, 2 injured",
        }),
      },
    ]);

    expect(screen.getByTestId("live-count").textContent).toContain("1 live");
    const cardEl = screen.getByTestId("call-card");
    expect(cardEl.getAttribute("data-severity")).toBe("CRITICAL");
    expect(screen.getByText("Accident, 2 injured")).toBeTruthy();
  });
});
