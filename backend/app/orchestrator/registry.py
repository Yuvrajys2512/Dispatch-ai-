"""Live-session registry — find a running :class:`CallSession` by call id.

The take-over trigger (a dashboard WebSocket message or the REST endpoint) needs
to reach the in-flight session for a call. Sessions register themselves on start
and deregister on end; the registry is just a process-local dict because one
backend process owns all live calls in this phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models import Call
    from app.orchestrator.session import CallSession


class SessionRegistry:
    """Maps a public ``call_id`` to its live :class:`CallSession`."""

    def __init__(self) -> None:
        self._sessions: dict[str, CallSession] = {}

    def register(self, session: CallSession) -> None:
        self._sessions[session.call_id] = session

    def deregister(self, call_id: str) -> None:
        self._sessions.pop(call_id, None)

    def get(self, call_id: str) -> CallSession | None:
        return self._sessions.get(call_id)

    def active_ids(self) -> list[str]:
        return list(self._sessions)

    def live_calls(self) -> list[Call]:
        """Snapshot the live :class:`Call` of every running session.

        Used by the dashboard's initial-hydration endpoint so a client that
        connects mid-stream sees the calls already in flight, not just the ones
        that emit a fresh ``call.started`` after it subscribes.
        """
        return [session.call for session in self._sessions.values()]


# Process-wide default registry used by the simulator + the takeover endpoint.
default_registry = SessionRegistry()
