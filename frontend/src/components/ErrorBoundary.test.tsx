import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

// Module-level flag lets us flip whether the child throws without a rerender.
let boom = false;
const ControlledBoom = () => {
  if (boom) throw new Error("test crash");
  return <div data-testid="child">ok</div>;
};

describe("ErrorBoundary", () => {
  beforeEach(() => {
    boom = false;
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("renders children when there is no error", () => {
    render(
      <ErrorBoundary>
        <ControlledBoom />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("child")).toBeTruthy();
  });

  it("renders the error screen when a child crashes", () => {
    boom = true;
    render(
      <ErrorBoundary>
        <ControlledBoom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Dashboard error")).toBeTruthy();
    expect(screen.getByText("test crash")).toBeTruthy();
  });

  it("recovers when retry is clicked and the error condition is gone", () => {
    boom = true;
    render(
      <ErrorBoundary>
        <ControlledBoom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Dashboard error")).toBeTruthy();

    boom = false;
    fireEvent.click(screen.getByText("Retry"));
    expect(screen.getByTestId("child")).toBeTruthy();
  });
});
