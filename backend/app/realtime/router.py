"""FastAPI wiring for the realtime layer — the WebSocket stream + take-over API.

* ``GET /ws/events`` — a dashboard client opens this WebSocket and receives the
  ordered, typed event stream (every call's events fan out here). The client may
  also send ``{"action": "takeover", "call_id": "..."}`` to bridge a human into a
  live call.
* ``POST /api/calls/{call_id}/takeover`` — the same trigger as a plain REST call,
  for clients that aren't on the socket.

Both resolve the live :class:`~app.orchestrator.session.CallSession` through the
default :class:`~app.orchestrator.registry.SessionRegistry`.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import RequireKey
from app.config import settings
from app.orchestrator.registry import default_registry
from app.realtime.hub import default_hub

logger = logging.getLogger("dispatch.ws")

router = APIRouter()


async def _trigger_takeover(call_id: str, reason: str) -> bool:
    session = default_registry.get(call_id)
    if session is None:
        return False
    await session.take_over(reason=reason)
    return True


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket) -> None:
    """Stream the live event feed; accept take-over actions from the client."""
    expected = settings.dispatch_api_key
    if expected:
        key = websocket.query_params.get("key", "")
        if key != expected:
            await websocket.close(code=1008)  # Policy Violation
            return
    await websocket.accept()
    async with default_hub.subscribe() as queue:

        async def _pump() -> None:
            while True:
                event = await queue.get()
                await websocket.send_json(event.model_dump(mode="json"))

        pump = asyncio.create_task(_pump())
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("action") == "takeover" and message.get("call_id"):
                    ok = await _trigger_takeover(
                        message["call_id"], message.get("reason", "dashboard takeover")
                    )
                    await websocket.send_json({"ack": "takeover", "ok": ok})
        except WebSocketDisconnect:
            logger.info("ws client disconnected")
        finally:
            pump.cancel()


@router.post("/api/calls/{call_id}/takeover", dependencies=[RequireKey])
async def takeover(call_id: str) -> dict:
    """Bridge a human operator into a live call (REST trigger)."""
    ok = await _trigger_takeover(call_id, reason="operator takeover (API)")
    return {"call_id": call_id, "taken_over": ok}


@router.get("/api/calls/active", dependencies=[RequireKey])
async def active_calls() -> dict:
    """List the call ids currently running in this process."""
    return {"active": default_registry.active_ids()}


@router.get("/api/calls/live", dependencies=[RequireKey])
async def live_calls() -> dict:
    """Full live ``Call`` snapshots for dashboard hydration.

    A dashboard that connects mid-stream needs the calls already in flight, not
    just the ids. Each entry is a domain :class:`~app.domain.models.Call`
    serialized to JSON — the same shape embedded in ``incident.updated`` events,
    so the client reducer can fold these in identically.
    """
    calls = default_registry.live_calls()
    return {"calls": [call.model_dump(mode="json") for call in calls]}
