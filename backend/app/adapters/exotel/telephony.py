"""Exotel telephony adapter — inbound calls, bidirectional media, bridge, hangup.

Honors :class:`~app.adapters.base.TelephonyProvider`. Unlike the mock (which *is*
the call source), real calls arrive from outside: Exotel hits a webhook and opens a
bidirectional **media WebSocket**. So this provider is a small hub — the intake
route (``intake.py``) hands it each new call via :meth:`offer_call`, and the rest of
the pipeline consumes it through the unchanged protocol:

* :meth:`incoming_calls` drains offered calls (real-mode analogue of the mock's
  per-scenario stream);
* :meth:`caller_audio` yields inbound media frames from that call's socket;
* :meth:`send_audio` writes outbound (TTS) frames back over the socket;
* :meth:`bridge_to_operator` / :meth:`hangup` issue Exotel REST calls (and record
  the effect, like the mock, so tests/the dashboard can observe them).

The media transport (:class:`MediaSocket`) and the REST surface
(:class:`ExotelClient`) are both injected, so the contract tests use an in-memory
fake socket + a recording client — no real telephony, no credentials.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.adapters.base import AudioChunk, IncomingCall

logger = logging.getLogger("dispatch.exotel")

# Sentinel offered to cleanly end the incoming-calls stream (tests / shutdown).
_STOP = object()


@runtime_checkable
class MediaSocket(Protocol):
    """One call's bidirectional media stream (Exotel media WS, or a test fake)."""

    def inbound(self) -> AsyncIterator[AudioChunk]:
        """Inbound caller audio frames until the caller stops / hangs up."""
        ...

    async def send(self, audio: AudioChunk) -> None:
        """Send one outbound (AI/TTS) audio frame to the caller."""
        ...

    async def aclose(self) -> None:
        """Close the media stream."""
        ...


@runtime_checkable
class ExotelClient(Protocol):
    """Exotel's call-control REST surface (bridge to operator, hang up, record)."""

    async def connect_to_operator(self, call_id: str, operator_number: str) -> None: ...

    async def hangup(self, call_id: str) -> None: ...

    async def start_recording(self, call_id: str) -> None: ...


class ExotelTelephonyProvider:
    def __init__(
        self,
        client: ExotelClient,
        *,
        operator_number: str = "",
        record: bool = True,
    ) -> None:
        self._client = client
        self._operator_number = operator_number
        self._record = record
        # Offered calls awaiting pickup; sockets keyed by call id.
        self._offers: list = []
        self._offer_event = _AsyncSignal()
        self._sockets: dict[str, MediaSocket] = {}
        # Observable side effects (parity with the mock).
        self.sent_audio: dict[str, list[AudioChunk]] = {}
        self.bridged: set[str] = set()
        self.hung_up: set[str] = set()
        self.recorded: set[str] = set()

    # --- intake hooks ----------------------------------------------------

    def offer_call(self, call: IncomingCall, socket: MediaSocket) -> None:
        """Register a new inbound call + its media socket (called by intake)."""
        self._sockets[call.call_id] = socket
        self.sent_audio.setdefault(call.call_id, [])
        self._offers.append(call)
        self._offer_event.set()

    def close(self) -> None:
        """Signal that no more calls will arrive; ends ``incoming_calls``."""
        self._offers.append(_STOP)
        self._offer_event.set()

    # --- TelephonyProvider ----------------------------------------------

    async def incoming_calls(self) -> AsyncIterator[IncomingCall]:
        while True:
            while self._offers:
                item = self._offers.pop(0)
                if item is _STOP:
                    return
                if self._record:
                    await self._safe(self._client.start_recording(item.call_id))
                    self.recorded.add(item.call_id)
                yield item
            await self._offer_event.wait()
            self._offer_event.clear()

    async def caller_audio(self, call_id: str) -> AsyncIterator[AudioChunk]:
        socket = self._sockets[call_id]
        async for chunk in socket.inbound():
            yield chunk

    async def send_audio(self, call_id: str, audio: AudioChunk) -> None:
        self.sent_audio.setdefault(call_id, []).append(audio)
        socket = self._sockets.get(call_id)
        if socket is not None:
            await self._safe(socket.send(audio))

    async def bridge_to_operator(self, call_id: str) -> None:
        self.bridged.add(call_id)
        if self._operator_number:
            await self._safe(
                self._client.connect_to_operator(call_id, self._operator_number)
            )

    async def hangup(self, call_id: str) -> None:
        self.hung_up.add(call_id)
        await self._safe(self._client.hangup(call_id))
        socket = self._sockets.pop(call_id, None)
        if socket is not None:
            await self._safe(socket.aclose())

    @staticmethod
    async def _safe(coro) -> None:
        """Outbound telephony ops are best-effort — never crash a live call."""
        try:
            await coro
        except Exception:  # noqa: BLE001
            logger.exception("exotel call-control op failed (continuing)")


class _AsyncSignal:
    """A tiny resettable async event (avoids losing sets between waits)."""

    def __init__(self) -> None:
        import asyncio

        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    async def wait(self) -> None:
        await self._event.wait()


# --- Real Exotel REST client ---------------------------------------------

class HttpExotelClient:
    """Thin Exotel call-control client (used in real mode; live-gated)."""

    def __init__(self, client, *, sid: str) -> None:
        self._client = client
        self._sid = sid

    async def connect_to_operator(self, call_id: str, operator_number: str) -> None:
        await self._client.post(
            f"/v1/Accounts/{self._sid}/Calls/connect",
            data={"CallSid": call_id, "To": operator_number},
        )

    async def hangup(self, call_id: str) -> None:
        await self._client.post(
            f"/v1/Accounts/{self._sid}/Calls/{call_id}/hangup", data={}
        )

    async def start_recording(self, call_id: str) -> None:
        await self._client.post(
            f"/v1/Accounts/{self._sid}/Calls/{call_id}/record", data={"Record": "true"}
        )


def build_exotel_telephony(
    *,
    sid: str,
    token: str,
    api_base: str,
    operator_number: str,
    record: bool,
) -> ExotelTelephonyProvider:
    import httpx

    http = httpx.AsyncClient(
        base_url=api_base, auth=(sid, token), timeout=httpx.Timeout(10.0)
    )
    client = HttpExotelClient(http, sid=sid)
    return ExotelTelephonyProvider(
        client, operator_number=operator_number, record=record
    )
