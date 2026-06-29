import type { AnalyticsSummary } from "../types/analytics";
import type { Call } from "../types/events";

// Backend base URL. In dev the Vite proxy forwards /api; for the health probe
// and the WebSocket we hit the backend directly (CORS is enabled server-side).
export const BACKEND_URL =
  import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8001";

// Optional API key (set via VITE_API_KEY in production). When empty, auth is
// disabled on the backend and no credential is sent.
const API_KEY: string = import.meta.env.VITE_API_KEY ?? "";

/** Auth header for REST calls when an API key is configured. */
function authHeaders(): HeadersInit {
  return API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {};
}

/** WebSocket URL — appends ?key= when auth is configured. */
export const WS_URL = API_KEY
  ? `${BACKEND_URL.replace(/^http/, "ws")}/ws/events?key=${encodeURIComponent(API_KEY)}`
  : `${BACKEND_URL.replace(/^http/, "ws")}/ws/events`;

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  provider_mode: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BACKEND_URL}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

/** Full snapshots of calls already in flight — for initial dashboard hydration. */
export async function fetchLiveCalls(): Promise<Call[]> {
  const res = await fetch(`${BACKEND_URL}/api/calls/live`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Live-calls fetch failed: ${res.status}`);
  const body = (await res.json()) as { calls: Call[] };
  return body.calls;
}

/** Day-level ops analytics for the dashboard footer — polled like /health. */
export async function fetchAnalytics(): Promise<AnalyticsSummary> {
  const res = await fetch(`${BACKEND_URL}/api/analytics/summary`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Analytics fetch failed: ${res.status}`);
  return res.json();
}

export interface TakeoverResponse {
  call_id: string;
  taken_over: boolean;
}

/** Bridge a human operator into a live call (REST trigger). */
export async function postTakeover(callId: string): Promise<TakeoverResponse> {
  const res = await fetch(
    `${BACKEND_URL}/api/calls/${encodeURIComponent(callId)}/takeover`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Takeover failed: ${res.status}`);
  return res.json();
}
