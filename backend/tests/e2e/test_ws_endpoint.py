"""WebSocket + take-over API wiring (realtime/router.py).

Thin coverage of the FastAPI surface: the event WebSocket accepts a take-over
action and acks it, and the REST endpoints resolve the live-session registry.
The event fan-out itself is exercised end-to-end in ``test_call_lifecycle.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_ws_takeover_action_acks():
    client = TestClient(app)
    with client.websocket_connect("/ws/events") as ws:
        ws.send_json({"action": "takeover", "call_id": "does-not-exist"})
        ack = ws.receive_json()
    assert ack == {"ack": "takeover", "ok": False}


def test_takeover_rest_unknown_call():
    client = TestClient(app)
    resp = client.post("/api/calls/does-not-exist/takeover")
    assert resp.status_code == 200
    assert resp.json() == {"call_id": "does-not-exist", "taken_over": False}


def test_active_calls_endpoint():
    client = TestClient(app)
    resp = client.get("/api/calls/active")
    assert resp.status_code == 200
    assert isinstance(resp.json()["active"], list)


def test_live_calls_endpoint_empty():
    client = TestClient(app)
    resp = client.get("/api/calls/live")
    assert resp.status_code == 200
    assert resp.json() == {"calls": []}


def test_live_calls_endpoint_serializes_registered_session():
    """A registered session surfaces as a full, JSON-serializable Call snapshot."""
    from app.adapters.base import IncomingCall
    from app.orchestrator.registry import default_registry
    from app.orchestrator.session import CallSession

    incoming = IncomingCall(
        call_id="mock-live-test", from_number="+91-98100-00042", metadata={}
    )
    session = CallSession.__new__(CallSession)
    # Minimal hand-built session: the live-calls endpoint only reads ``.call``.
    from app.domain.models import Call

    session._call = Call(phone=incoming.from_number)  # type: ignore[attr-defined]
    default_registry.register(session)
    try:
        resp = client_get_live()
        body = resp.json()
        assert resp.status_code == 200
        phones = [c["phone"] for c in body["calls"]]
        assert "+91-98100-00042" in phones
        # Snapshot carries the live state machine position + empty card.
        snap = next(c for c in body["calls"] if c["phone"] == "+91-98100-00042")
        assert snap["state"] == "GREETING"
        assert snap["incident"]["severity"] == "MEDIUM"
    finally:
        default_registry.deregister(session.call_id)


def client_get_live():
    return TestClient(app).get("/api/calls/live")
