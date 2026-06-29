import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnalyticsBar } from "./AnalyticsBar";
import type { Analytics } from "../store/selectors";
import type { AnalyticsSummary } from "../types/analytics";

const session: Analytics = {
  live: 2,
  totalStarted: 9,
  ended: 7,
  junk: 3,
  autoResolved: 2,
  junkPct: 33,
};

function day(over: Partial<AnalyticsSummary> = {}): AnalyticsSummary {
  return {
    total_calls: 12,
    junk_calls: 4,
    junk_pct: 33.3,
    auto_resolved: 3,
    avg_ai_handle_seconds: 95,
    severity_distribution: {
      CRITICAL: 2,
      HIGH: 1,
      MEDIUM: 2,
      LOW: 3,
      JUNK: 4,
    },
    calls_per_hour: { 9: 5, 11: 7 },
    window_start: "2026-06-24T00:00:00+05:30",
    generated_at: "2026-06-24T15:00:00+05:30",
    ...over,
  };
}

describe("AnalyticsBar", () => {
  it("shows a loading hint until the first day-level fetch lands", () => {
    render(<AnalyticsBar stats={session} day={null} />);
    expect(screen.getByTestId("analytics-loading")).toBeTruthy();
    // Session numbers render regardless of the day-level fetch.
    expect(screen.getByText("started")).toBeTruthy();
  });

  it("renders real day-level numbers and formats avg AI handle time", () => {
    render(<AnalyticsBar stats={session} day={day()} />);
    expect(screen.queryByTestId("analytics-loading")).toBeNull();
    // total calls today
    expect(screen.getByText("12")).toBeTruthy();
    // junk % comes from the day payload, not the session counter
    expect(screen.getByText("33.3%")).toBeTruthy();
    // 95s → "1m 35s"
    expect(screen.getByText("1m 35s")).toBeTruthy();
    // session live count still present
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("renders an em dash for zero handle time", () => {
    render(
      <AnalyticsBar stats={session} day={day({ avg_ai_handle_seconds: 0 })} />,
    );
    expect(screen.getByText("—")).toBeTruthy();
  });
});
