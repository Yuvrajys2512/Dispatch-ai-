"""Orchestrator — the live, streaming, per-call session (Phase 4).

:class:`CallSession` wires the adapters (telephony → ASR → agent → TTS) into one
async task, emits the realtime event stream, instruments per-hop latency, and
persists the call. :class:`SessionRegistry` lets the take-over trigger find a
running session by id.
"""

from app.orchestrator.latency import LatencyTracker
from app.orchestrator.registry import SessionRegistry, default_registry
from app.orchestrator.session import CallSession

__all__ = [
    "CallSession",
    "LatencyTracker",
    "SessionRegistry",
    "default_registry",
]
