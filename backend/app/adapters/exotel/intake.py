"""Real call-intake path — the real-mode analogue of the simulator.

The simulator (``app/simulator``) is the *mock* call source: it builds a
:class:`~app.orchestrator.session.CallSession` per scripted scenario. This module
is its real twin: an Exotel **webhook** (inbound call) plus a bidirectional **media
WebSocket** build an :class:`~app.adapters.base.IncomingCall` + the audio streams,
and run the **same** ``CallSession`` — same orchestrator, same events, same
persistence, same dashboard. Only the *source* of the call differs.

:class:`ExotelIntake` is the testable core (drive it with a fake media socket and a
recording Exotel client — no real telephony). The FastAPI routes at the bottom are
the thin live shell that mounts in ``main.py``; they are exercised by a real phone
call in the final, credential-gated mile.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.adapters.base import ASRProvider, AudioChunk, IncomingCall, TTSProvider
from app.adapters.exotel.telephony import ExotelTelephonyProvider
from app.agent.triage import TriageAgent
from app.db.caller_counter import CallerCallCounter
from app.db.redis_store import CallStateStore, get_redis
from app.db.session import session_scope
from app.domain.models import Call
from app.orchestrator.registry import SessionRegistry, default_registry
from app.orchestrator.session import CallSession, SessionFactory
from app.realtime.hub import EventHub, default_hub

logger = logging.getLogger("dispatch.exotel.intake")


class ExotelIntake:
    """Runs a ``CallSession`` for each real inbound call (bounded concurrency)."""

    def __init__(
        self,
        *,
        telephony: ExotelTelephonyProvider,
        asr: ASRProvider,
        tts: TTSProvider,
        agent: TriageAgent,
        hub: EventHub | None = None,
        store: CallStateStore | None = None,
        registry: SessionRegistry | None = None,
        session_factory: SessionFactory = session_scope,
        counter: CallerCallCounter | None = None,
        concurrency: int = 5,
    ) -> None:
        self._tel = telephony
        self._asr = asr
        self._tts = tts
        self._agent = agent
        self._hub = hub or default_hub
        self._store = store or CallStateStore(get_redis())
        self._registry = registry or default_registry
        self._session_factory = session_factory
        self._counter = counter or CallerCallCounter(self._store.client)
        self._semaphore = asyncio.Semaphore(concurrency)

    def _build_session(self, incoming: IncomingCall) -> CallSession:
        return CallSession(
            incoming,
            telephony=self._tel,
            asr=self._asr,
            tts=self._tts,
            agent=self._agent,
            hub=self._hub,
            store=self._store,
            session_factory=self._session_factory,
            registry=self._registry,
            caller_counter=self._counter,
        )

    async def handle_call(self, incoming: IncomingCall) -> Call:
        """Run one inbound call to a terminal state (the testable unit)."""
        async with self._semaphore:
            logger.info("handling real call %s from %s", incoming.call_id, incoming.from_number)
            return await self._build_session(incoming).run()

    async def run(self) -> None:
        """Consume offered inbound calls forever, one CallSession each."""
        tasks: set[asyncio.Task] = set()
        async for incoming in self._tel.incoming_calls():
            task = asyncio.create_task(self.handle_call(incoming))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# --- FastAPI live shell (mounted in main.py; exercised by a real call) ----

def _incoming_from_start(event: dict) -> IncomingCall:
    """Build an IncomingCall from Exotel's media-stream ``start`` event."""
    start = event.get("start", event)
    call_id = start.get("call_sid") or start.get("callSid") or start.get("stream_sid", "")
    frm = start.get("from") or start.get("From") or "unknown"
    to = start.get("to") or start.get("To") or "112"
    return IncomingCall(
        call_id=str(call_id), from_number=str(frm), to_number=str(to),
        metadata={"source": "exotel"},
    )


class _StarletteMediaSocket:
    """Wraps a live Exotel media WebSocket in the :class:`MediaSocket` shape.

    Exotel streams base64 PCM in JSON ``media`` events and a terminal ``stop``
    event; outbound audio is sent back as ``media`` events. (Live-gated path.)
    """

    def __init__(self, websocket) -> None:
        import base64

        self._ws = websocket
        self._b64 = base64
        self._closed = asyncio.Event()

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def inbound(self) -> AsyncIterator[AudioChunk]:
        seq = 0
        while True:
            try:
                event = await self._ws.receive_json()
            except Exception:  # noqa: BLE001 - socket closed/aborted
                return
            kind = event.get("event")
            if kind == "media":
                payload = self._b64.b64decode(event["media"]["payload"])
                seq += 1
                yield AudioChunk(payload=payload, seq=seq, is_last=True)
            elif kind in ("stop", "disconnect"):
                return

    async def send(self, audio: AudioChunk) -> None:
        if self._closed.is_set():
            return
        await self._ws.send_json(
            {"event": "media", "media": {"payload": self._b64.b64encode(audio.payload).decode()}}
        )

    async def aclose(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            await self._ws.close()
        except Exception:  # noqa: BLE001
            pass


def build_intake_router(intake: ExotelIntake, telephony: ExotelTelephonyProvider):
    """Build the FastAPI router for the live Exotel webhook + media WS."""
    from fastapi import APIRouter, Request, WebSocket

    router = APIRouter()

    @router.post("/exotel/voice")
    async def voice_webhook(request: Request) -> dict:
        """Inbound-call webhook; ack so Exotel proceeds to the media stream."""
        form = dict((await request.form()).items()) if request.headers.get(
            "content-type", ""
        ).startswith("application/x-www-form-urlencoded") else {}
        logger.info("exotel inbound call webhook: %s", form.get("CallSid"))
        return {"status": "ok"}

    @router.websocket("/exotel/media")
    async def media_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        start = await websocket.receive_json()
        incoming = _incoming_from_start(start)
        socket = _StarletteMediaSocket(websocket)
        # Hand the call to the running intake loop (which builds the CallSession);
        # keep this coroutine alive until the session closes the media socket.
        telephony.offer_call(incoming, socket)
        await socket.wait_closed()

    return router
