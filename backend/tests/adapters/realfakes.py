"""In-memory transport/socket fakes for the **real** adapters' contract tests.

The real adapters reach the public internet; the test suite must not. So each fake
here stands in for one provider's wire transport and is wired *behind* the real
adapter — the adapter's own parsing/streaming logic runs for real, only the network
is replaced. Where useful, a fake replays the mock provider's deterministic logic,
so the real adapter passes the very same contract assertions as the mock (true
contract parity, no relaxed tests).
"""

from __future__ import annotations

import base64
import contextlib
import json
import math
from collections.abc import AsyncIterator

import httpx
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.adapters.base import AudioChunk, IncomingCall
from app.adapters.exotel.telephony import ExotelTelephonyProvider
from app.adapters.llm.anthropic_llm import AnthropicLLMProvider
from app.adapters.mock.llm import MockLLMProvider
from app.adapters.sarvam.asr import SarvamASRProvider
from app.adapters.sarvam.tts import SarvamTTSProvider

# --- LLM: a fake Anthropic transport that replays the mock rule engine -----

_mock_llm = MockLLMProvider()


def _user_text(body: dict) -> str:
    content = body["messages"][0]["content"]
    text = content if isinstance(content, str) else content[0].get("text", "")
    # The real adapter substitutes a parenthetical placeholder for empty input;
    # map it back to "" so the replayed mock logic matches (e.g. the 112 greeting).
    if text.startswith("(") and text.endswith(")"):
        return ""
    return text


def _sse(text: str) -> bytes:
    tokens = [w if i == 0 else f" {w}" for i, w in enumerate(text.split())]
    lines = [
        "event: message_start\ndata: "
        + json.dumps(
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1", "type": "message", "role": "assistant",
                    "model": "claude-haiku-4-5-20251001", "content": [],
                    "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 0},
                },
            }
        ),
        "event: content_block_start\ndata: "
        + json.dumps(
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}}
        ),
    ]
    for tok in tokens:
        lines.append(
            "event: content_block_delta\ndata: "
            + json.dumps(
                {"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": tok}}
            )
        )
    lines += [
        "event: content_block_stop\ndata: "
        + json.dumps({"type": "content_block_stop", "index": 0}),
        "event: message_delta\ndata: "
        + json.dumps(
            {"type": "message_delta",
             "delta": {"stop_reason": "end_turn", "stop_sequence": None},
             "usage": {"output_tokens": len(tokens)}}
        ),
        "event: message_stop\ndata: " + json.dumps({"type": "message_stop"}),
    ]
    return ("\n\n".join(lines) + "\n\n").encode()


def _anthropic_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    text = _user_text(body)
    if body.get("stream"):
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=_sse(
                MockLLMProvider._response_for(text)
            )
        )
    derived = _mock_llm._derive(text)
    return httpx.Response(
        200,
        json={
            "id": "msg_1", "type": "message", "role": "assistant",
            "model": body["model"],
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "record_incident",
                 "input": derived}
            ],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        },
    )


def make_anthropic_provider() -> AnthropicLLMProvider:
    client = AsyncAnthropic(
        api_key="test",
        http_client=DefaultAsyncHttpxClient(transport=httpx.MockTransport(_anthropic_handler)),
    )
    return AnthropicLLMProvider(client, "claude-haiku-4-5-20251001")


# --- Sarvam ASR: an in-memory streaming-ASR socket -------------------------

FINAL_CONF = 0.92
PARTIAL_CONF = round(FINAL_CONF * 0.8, 2)
SILENCE_CONF = 0.2


def _partial_cuts(n: int) -> list[int]:
    if n <= 1:
        return []
    raw = {max(1, math.ceil(n * k / 3)) for k in (1, 2)}
    return [c for c in sorted(raw) if c < n]


class FakeASRSocket:
    """Replays received audio frames as partial→final transcript messages."""

    def __init__(self) -> None:
        import asyncio

        self._queue: asyncio.Queue = asyncio.Queue()
        self._words: list[str] = []
        self._t = 0

    def _flush(self, *, silent: bool) -> None:
        self._t += 5
        if silent or not self._words:
            self._queue.put_nowait(
                {"transcript": "", "is_final": True, "confidence": SILENCE_CONF, "t_ms": self._t}
            )
            self._words = []
            return
        for cut in _partial_cuts(len(self._words)):
            self._t += 3
            self._queue.put_nowait(
                {"transcript": " ".join(self._words[:cut]), "is_final": False,
                 "confidence": PARTIAL_CONF, "t_ms": self._t}
            )
        self._t += 3
        self._queue.put_nowait(
            {"transcript": " ".join(self._words), "is_final": True,
             "confidence": FINAL_CONF, "t_ms": self._t}
        )
        self._words = []

    async def send_audio(self, payload: bytes, *, is_last: bool) -> None:
        word = payload.decode("utf-8", errors="ignore").strip()
        if word:
            self._words.append(word)
        if is_last:
            self._flush(silent=not word and not self._words)

    async def signal_end(self) -> None:
        if self._words:
            self._flush(silent=False)
        self._queue.put_nowait(None)  # sentinel

    async def transcripts(self) -> AsyncIterator[dict]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item


def make_sarvam_asr_provider() -> SarvamASRProvider:
    @contextlib.asynccontextmanager
    async def connect():
        yield FakeASRSocket()

    return SarvamASRProvider(connect)


# --- Sarvam TTS: a fake REST transport returning base64 audio ---------------

def _tts_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    # Synthesize a clip whose length scales with the text, so multiple frames flow.
    raw = b"\x01\x02" * (256 * max(1, len(body.get("text", "").split())))
    return httpx.Response(200, json={"audios": [base64.b64encode(raw).decode()]})


def make_sarvam_tts_provider() -> SarvamTTSProvider:
    client = httpx.AsyncClient(
        base_url="https://fake.sarvam", transport=httpx.MockTransport(_tts_handler)
    )
    return SarvamTTSProvider(client, model="bulbul:v2", speaker="meera", language="hi-IN")


# --- Exotel: a recording REST client + an in-memory media socket -----------

class FakeExotelClient:
    def __init__(self) -> None:
        self.connected: list[tuple[str, str]] = []
        self.hung_up: list[str] = []
        self.recorded: list[str] = []

    async def connect_to_operator(self, call_id: str, operator_number: str) -> None:
        self.connected.append((call_id, operator_number))

    async def hangup(self, call_id: str) -> None:
        self.hung_up.append(call_id)

    async def start_recording(self, call_id: str) -> None:
        self.recorded.append(call_id)


class FakeMediaSocket:
    def __init__(self, frames: list[AudioChunk]) -> None:
        self._frames = frames
        self.sent: list[AudioChunk] = []
        self.closed = False

    async def inbound(self) -> AsyncIterator[AudioChunk]:
        for frame in self._frames:
            yield frame

    async def send(self, audio: AudioChunk) -> None:
        self.sent.append(audio)

    async def aclose(self) -> None:
        self.closed = True


def make_exotel_provider(
    *, operator_number: str = "+919900000000", record: bool = True
) -> tuple[ExotelTelephonyProvider, FakeExotelClient]:
    client = FakeExotelClient()
    provider = ExotelTelephonyProvider(
        client, operator_number=operator_number, record=record
    )
    return provider, client


def text_frames(text: str) -> list[AudioChunk]:
    """Build inbound media frames from text (synthetic codec, mirrors the mock)."""
    words = text.split()
    frames = []
    t = 0
    for i, word in enumerate(words):
        t += 2
        frames.append(
            AudioChunk.from_text(word, seq=i, t_ms=t, is_last=(i == len(words) - 1))
        )
    return frames


def incoming(call_id: str = "exo-1", from_number: str = "+919812345678") -> IncomingCall:
    return IncomingCall(call_id=call_id, from_number=from_number, metadata={"source": "exotel"})
