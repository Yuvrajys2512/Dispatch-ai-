// WebSocket lifecycle for the dashboard: hydrate → subscribe → reduce → reconnect.
//
// This is the only place that touches the network. It calls the pure store
// actions (`applyEvent`, `hydrate`, `setConnection`, `removeCall`); the store
// itself stays I/O-free and unit-testable. Reconnect uses capped exponential
// backoff; a `call.ended` schedules the card's removal after a short linger so a
// supervisor sees the resolution before the card disappears.

import { useEffect } from "react";
import { fetchLiveCalls, postTakeover, WS_URL } from "../lib/api";
import type { DispatchEvent } from "../types/events";
import { useCallStore } from "./callStore";

/** How long an ended call lingers on screen before it's removed. */
export const ENDED_LINGER_MS = 6000;

const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];
const MAX_BACKOFF_MS = 10000;

export interface DashboardConnection {
  close: () => void;
}

/**
 * Open and supervise the dashboard's live connection. Returns a handle whose
 * `close()` tears everything down (used by the React effect's cleanup).
 */
export function createDashboardConnection(
  url: string = WS_URL,
): DashboardConnection {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  const removalTimers = new Set<ReturnType<typeof setTimeout>>();
  let closed = false;

  const scheduleRemoval = (callId: string) => {
    const timer = setTimeout(() => {
      removalTimers.delete(timer);
      useCallStore.getState().removeCall(callId);
    }, ENDED_LINGER_MS);
    removalTimers.add(timer);
  };

  const handleMessage = (raw: string) => {
    let event: DispatchEvent;
    try {
      event = JSON.parse(raw) as DispatchEvent;
    } catch {
      return; // ignore non-JSON / ack frames
    }
    if (!event || typeof event.type !== "string") return;
    useCallStore.getState().applyEvent(event);
    if (event.type === "call.ended") scheduleRemoval(event.call_id);
  };

  const connect = () => {
    if (closed) return;
    useCallStore.getState().setConnection("connecting");
    // Best-effort hydration of in-flight calls before/at connect.
    fetchLiveCalls()
      .then((calls) => useCallStore.getState().hydrate(calls))
      .catch(() => {
        /* hydration is optional; the live stream backfills */
      });

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }
    socket = ws;

    ws.onopen = () => {
      attempt = 0;
      useCallStore.getState().setConnection("online");
    };
    ws.onmessage = (e) => handleMessage(String(e.data));
    ws.onerror = () => {
      // `onclose` follows and drives the reconnect; just surface offline.
      useCallStore.getState().setConnection("offline");
    };
    ws.onclose = () => {
      socket = null;
      if (closed) return;
      useCallStore.getState().setConnection("offline");
      scheduleReconnect();
    };
  };

  const scheduleReconnect = () => {
    if (closed || reconnectTimer) return;
    const delay = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)] ??
      MAX_BACKOFF_MS;
    attempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, Math.min(delay, MAX_BACKOFF_MS));
  };

  connect();

  return {
    close: () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      for (const t of removalTimers) clearTimeout(t);
      removalTimers.clear();
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
    },
  };
}

/**
 * Fire the take-over for a call. Uses the REST trigger; the backend then emits
 * `operator.takeover` + `call.ended(HANDED_OVER)`, so the card updates through
 * the same event path as everything else (no optimistic client-side guessing).
 */
export async function takeOver(callId: string): Promise<boolean> {
  try {
    const res = await postTakeover(callId);
    return res.taken_over;
  } catch {
    return false;
  }
}

/** React hook: open the live connection for the lifetime of the component. */
export function useDashboardConnection(): void {
  useEffect(() => {
    const conn = createDashboardConnection();
    return () => conn.close();
  }, []);
}
