import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CallCard } from "./CallCard";
import type { CallView } from "../store/callStore";
import type { IncidentCard } from "../types/events";

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

function view(over: Partial<CallView> = {}): CallView {
  return {
    callId: "c1",
    phone: "+91-98100-00001",
    scenario: "accident",
    incident: card({
      incident_type: "ACCIDENT",
      severity: "CRITICAL",
      confidence: 0.94,
      location_text: "NH-24, Ghaziabad",
      summary: "Accident, 2 injured",
    }),
    severity: "CRITICAL",
    route: null,
    state: "DETAILS",
    finals: [],
    partial: null,
    startedTs: 1000,
    endedTs: null,
    durationSeconds: null,
    takenOver: false,
    ended: false,
    lastSeq: 3,
    hadGap: false,
    ...over,
  };
}

describe("CallCard", () => {
  it("renders severity badge, phone, summary, confidence and duration", () => {
    render(<CallCard call={view()} now={1042} />);
    const badge = screen.getByTestId("severity-badge");
    expect(badge.getAttribute("data-severity")).toBe("CRITICAL");
    expect(screen.getByText("+91-98100-00001")).toBeTruthy();
    expect(screen.getByText("Accident, 2 injured")).toBeTruthy();
    expect(screen.getByText(/94%/)).toBeTruthy();
    // now - startedTs = 42s → "0:42"
    expect(screen.getByTestId("duration").textContent).toContain("0:42");
  });

  it("shows a working TAKE OVER affordance on a live call", () => {
    render(<CallCard call={view()} now={1010} />);
    const btn = screen.getByRole("button", { name: /TAKE OVER/i });
    expect((btn as HTMLButtonElement).disabled).toBe(false);
  });

  it("renders junk as auto-resolved with a REVIEW affordance", () => {
    render(
      <CallCard
        call={view({
          severity: "JUNK",
          ended: true,
          state: "RESOLVED",
          durationSeconds: 8,
          incident: card({ severity: "JUNK", summary: null }),
          route: {
            target: "AUTO_RESOLVE",
            severity: "JUNK",
            confidence: 0.95,
            reason: "junk",
            handoff: false,
          },
        })}
        now={2000}
      />,
    );
    expect(screen.getByTestId("auto-resolved").textContent).toContain(
      "Auto-resolved",
    );
    expect(screen.getByRole("button", { name: /REVIEW/i })).toBeTruthy();
    // No TAKE OVER button for an auto-resolved junk call.
    expect(screen.queryByRole("button", { name: /TAKE OVER/i })).toBeNull();
  });

  it("reflects an operator takeover (AI dropped, button disabled)", () => {
    render(
      <CallCard
        call={view({ takenOver: true, state: "HANDED_OVER" })}
        now={1010}
      />,
    );
    expect(screen.getByTestId("state-label").textContent).toContain(
      "HANDED OVER",
    );
    const btn = screen.getByRole("button", { name: /Handed over/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("uses the authoritative duration once the call ended", () => {
    render(
      <CallCard
        call={view({ ended: true, durationSeconds: 75, state: "ROUTED" })}
        now={999999}
      />,
    );
    expect(screen.getByTestId("duration").textContent).toContain("1:15");
  });
});
