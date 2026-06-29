import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount React trees between tests so component state never leaks across cases.
afterEach(() => cleanup());

// jsdom ships no WebSocket. Provide a minimal inert stub so mounting components
// that open the dashboard connection doesn't throw and doesn't touch a network.
// Tests that exercise the reducer drive the store directly with synthetic events.
if (typeof (globalThis as { WebSocket?: unknown }).WebSocket === "undefined") {
  class FakeWebSocket {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSING = 2;
    static readonly CLOSED = 3;
    readyState = FakeWebSocket.CONNECTING;
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: ((e: { data: string }) => void) | null = null;
    constructor(public url: string) {}
    send(): void {}
    close(): void {
      this.readyState = FakeWebSocket.CLOSED;
    }
  }
  (globalThis as { WebSocket?: unknown }).WebSocket =
    FakeWebSocket as unknown as typeof WebSocket;
}
