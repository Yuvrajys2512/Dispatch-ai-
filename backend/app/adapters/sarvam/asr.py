"""Sarvam streaming ASR adapter — audio frames in, partial→final transcripts out.

Honors :class:`~app.adapters.base.ASRProvider`. A streaming ASR is a WebSocket: you
push audio frames, the server streams back growing **partial** hypotheses and then
a **final** transcript per utterance (with a confidence). One ``stream_transcribe``
call spans the whole call, so it must keep emitting across *multiple* utterances —
exactly like the mock — not stop at the first final.

The socket is abstracted behind :class:`ASRSocket` and injected via a ``connect``
factory, so the contract tests drive an in-memory fake socket (no network, no key)
while production uses a real Sarvam WebSocket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from app.adapters.base import AudioChunk, TranscriptChunk

logger = logging.getLogger("dispatch.sarvam.asr")


@runtime_checkable
class ASRSocket(Protocol):
    """A bidirectional streaming-ASR connection (Sarvam WS, or a test fake)."""

    async def send_audio(self, payload: bytes, *, is_last: bool) -> None:
        """Push one audio frame; ``is_last`` marks the end of an utterance."""
        ...

    async def signal_end(self) -> None:
        """No more audio — flush and close the recognition stream."""
        ...

    def transcripts(self) -> AsyncIterator[dict]:
        """Stream of result dicts: ``{transcript, is_final, confidence, t_ms?}``."""
        ...


ConnectFactory = Callable[[], AbstractAsyncContextManager[ASRSocket]]


class SarvamASRProvider:
    def __init__(self, connect: ConnectFactory) -> None:
        self._connect = connect

    async def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[TranscriptChunk]:
        async with self._connect() as sock:

            async def _pump() -> None:
                async for chunk in audio:
                    await sock.send_audio(chunk.payload, is_last=chunk.is_last)
                await sock.signal_end()

            pump = asyncio.create_task(_pump())
            try:
                async for msg in sock.transcripts():
                    yield TranscriptChunk(
                        text=msg.get("transcript", ""),
                        is_final=bool(msg.get("is_final", False)),
                        confidence=float(msg.get("confidence", 0.0)),
                        t_ms=int(msg.get("t_ms", 0)),
                    )
                await pump
            finally:
                if not pump.done():
                    pump.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pump


# --- Real Sarvam WebSocket connection ------------------------------------

def build_sarvam_asr(
    *, api_key: str, api_base: str, language: str, model: str
) -> SarvamASRProvider:
    """Build the real provider; the WS connection opens lazily per call."""

    ws_base = api_base.replace("https://", "wss://").replace("http://", "ws://")
    url = f"{ws_base}/speech-to-text/ws?model={model}&language-code={language}"

    @contextlib.asynccontextmanager
    async def connect() -> AsyncIterator[ASRSocket]:
        import json

        import websockets

        conn = await websockets.connect(
            url, additional_headers={"api-subscription-key": api_key}
        )
        sock = _RealSarvamASRSocket(conn, json)
        try:
            yield sock
        finally:
            await conn.close()

    return SarvamASRProvider(connect)


class _RealSarvamASRSocket:
    """Wraps a live Sarvam WebSocket in the :class:`ASRSocket` shape."""

    def __init__(self, conn, json_mod) -> None:
        self._conn = conn
        self._json = json_mod

    async def send_audio(self, payload: bytes, *, is_last: bool) -> None:
        await self._conn.send(payload)
        if is_last:
            await self._conn.send(self._json.dumps({"event": "utterance_end"}))

    async def signal_end(self) -> None:
        await self._conn.send(self._json.dumps({"event": "end"}))

    async def transcripts(self) -> AsyncIterator[dict]:
        async for raw in self._conn:
            data = self._json.loads(raw)
            if data.get("type") == "transcript" or "transcript" in data:
                yield data
            if data.get("type") == "end":
                return
