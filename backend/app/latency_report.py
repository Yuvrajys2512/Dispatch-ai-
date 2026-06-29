"""End-to-end latency harness — per-hop measured-vs-budget table (Phase 7).

Runs a call's round trips through the **real** adapter code paths and feeds the
existing :class:`~app.orchestrator.latency.LatencyTracker`, then prints the spec's
budget table::

    network (audio->server) ~100ms · ASR <300 · LLM <400 · TTS first byte <300 ·
    network (audio->caller) ~100ms  =>  round-trip < 1500ms

Two modes:

* default (``--stub``) — infra-free: the real Sarvam/Anthropic/Exotel adapters run
  with **stubbed transports**, so this verifies the instrumentation + per-hop wiring
  end to end with no accounts. The numbers are tiny (no real network/models).
* ``--real`` — uses the live providers via the factory (``PROVIDER_MODE=real`` +
  keys). This is the number that proves the <1500ms budget on a real call; run it
  during the credential-gated live mile.

Run: ``python -m app.latency_report`` (add ``--turns N`` / ``--real``).

Windows console is cp1252, so the table is pure ASCII (no Unicode glyphs).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from time import perf_counter

import httpx
from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient

from app.adapters.base import AudioChunk
from app.adapters.exotel.telephony import ExotelTelephonyProvider
from app.adapters.llm.anthropic_llm import AnthropicLLMProvider
from app.adapters.sarvam.asr import SarvamASRProvider
from app.adapters.sarvam.tts import SarvamTTSProvider
from app.agent.signals import CallerTurn
from app.agent.triage import TriageAgent
from app.orchestrator.latency import BUDGET_MS, ROUND_TRIP_TARGET_MS, LatencyTracker

TURNS = [
    "accident ho gaya",
    "do log ghayal hain khoon nikal raha hai",
    "sector 14 ke paas, jaldi bhejiye",
]


# --- Stubbed transports (infra-free real-adapter exercise) ----------------

def _llm_stub() -> AnthropicLLMProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("stream"):
            text = "Madad bhej raha hoon. Aap line pe baney rahiye."
            tokens = [w if i == 0 else f" {w}" for i, w in enumerate(text.split())]
            parts = [
                'event: message_start\ndata: ' + json.dumps({
                    "type": "message_start", "message": {
                        "id": "m", "type": "message", "role": "assistant",
                        "model": body["model"], "content": [], "stop_reason": None,
                        "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 0}}}),
                'event: content_block_start\ndata: ' + json.dumps({
                    "type": "content_block_start", "index": 0,
                    "content_block": {"type": "text", "text": ""}}),
            ]
            for tok in tokens:
                parts.append('event: content_block_delta\ndata: ' + json.dumps({
                    "type": "content_block_delta", "index": 0,
                    "delta": {"type": "text_delta", "text": tok}}))
            parts += [
                'event: content_block_stop\ndata: '
                + json.dumps({"type": "content_block_stop", "index": 0}),
                'event: message_delta\ndata: ' + json.dumps({
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": len(tokens)}}),
                'event: message_stop\ndata: ' + json.dumps({"type": "message_stop"}),
            ]
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=("\n\n".join(parts) + "\n\n").encode())
        return httpx.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "tool_use", "id": "t", "name": "record_incident",
                         "input": {"incident_type": "ACCIDENT", "needs_ambulance": True,
                                   "summary": "accident"}}],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}})

    client = AsyncAnthropic(
        api_key="stub",
        http_client=DefaultAsyncHttpxClient(transport=httpx.MockTransport(handler)),
    )
    return AnthropicLLMProvider(client, "claude-haiku-4-5-20251001")


def _asr_stub() -> SarvamASRProvider:
    class _Sock:
        def __init__(self) -> None:
            self._q: asyncio.Queue = asyncio.Queue()
            self._words: list[str] = []

        async def send_audio(self, payload: bytes, *, is_last: bool) -> None:
            w = payload.decode("utf-8", errors="ignore").strip()
            if w:
                self._words.append(w)
            if is_last and self._words:
                self._q.put_nowait({"transcript": " ".join(self._words[:1]),
                                    "is_final": False, "confidence": 0.7})
                self._q.put_nowait({"transcript": " ".join(self._words),
                                    "is_final": True, "confidence": 0.92})
                self._words = []

        async def signal_end(self) -> None:
            self._q.put_nowait(None)

        async def transcripts(self) -> AsyncIterator[dict]:
            while True:
                item = await self._q.get()
                if item is None:
                    return
                yield item

    @contextlib.asynccontextmanager
    async def connect():
        yield _Sock()

    return SarvamASRProvider(connect)


def _tts_stub() -> SarvamTTSProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        raw = b"\x00\x01" * 1024
        return httpx.Response(200, json={"audios": [base64.b64encode(raw).decode()]})

    client = httpx.AsyncClient(base_url="https://stub", transport=httpx.MockTransport(handler))
    return SarvamTTSProvider(client, model="bulbul:v2", speaker="meera", language="hi-IN")


class _NoopExotelClient:
    async def connect_to_operator(self, call_id, operator_number): ...
    async def hangup(self, call_id): ...
    async def start_recording(self, call_id): ...


async def _text_audio(text: str) -> AsyncIterator[AudioChunk]:
    words = text.split()
    for i, word in enumerate(words):
        await asyncio.sleep(0)  # yield to the loop (mirror frame pacing)
        yield AudioChunk.from_text(word, seq=i, t_ms=(i + 1) * 2, is_last=(i == len(words) - 1))


async def run_report(*, turns: int, real: bool) -> LatencyTracker:
    if real:
        from app.adapters.factory import (
            get_asr_provider,
            get_llm_provider,
            get_tts_provider,
        )

        asr, tts, llm = get_asr_provider(), get_tts_provider(), get_llm_provider()
        telephony = ExotelTelephonyProvider(_NoopExotelClient())
    else:
        asr, tts, llm = _asr_stub(), _tts_stub(), _llm_stub()
        telephony = ExotelTelephonyProvider(_NoopExotelClient())

    call_id = "latency-harness"
    telephony.sent_audio[call_id] = []
    agent = TriageAgent(llm)
    tracker = LatencyTracker(call_id=call_id)

    history: list[CallerTurn] = []
    for i in range(turns):
        text = TURNS[i % len(TURNS)]

        # network in (caller audio -> server) + ASR
        t0 = perf_counter()
        finals: list = []
        async for chunk in asr.stream_transcribe(_text_audio(text)):
            if chunk.is_final:
                finals.append(chunk)
        tracker.record("asr", (perf_counter() - t0) * 1000.0)
        final = finals[-1]
        history.append(CallerTurn(text=final.text, confidence=final.confidence))

        # LLM / agent turn
        with tracker.measure("llm"):
            outcome = await agent.triage(history)

        # TTS first byte + network out (audio -> caller)
        line = outcome.dialogue[min(1, len(outcome.dialogue) - 1)].ai_line
        with tracker.measure("tts"):
            async for frame in tts.stream_synthesize(line):
                with tracker.measure("network"):
                    await telephony.send_audio(call_id, frame)

    return tracker


def _print_table(tracker: LatencyTracker, *, real: bool) -> None:
    n = max((len(v) for v in tracker.samples_ms.values()), default=0)
    mode = "real providers" if real else "transport-stubbed"
    print(f"Dispatch AI - latency budget ({mode}) - avg over {n} hop sample(s):")
    print(f"  {'hop':<12}{'measured':>12}{'budget':>10}{'verdict':>9}")
    for hop, budget in BUDGET_MS.items():
        measured = tracker.average_ms(hop)
        verdict = "OK" if measured < budget else "OVER"
        print(f"  {hop:<12}{measured:>10.1f}ms{budget:>8.1f}ms{verdict:>9}")
    rt = tracker.round_trip_ms()
    verdict = "OK" if rt < ROUND_TRIP_TARGET_MS else "OVER"
    print(f"  {'round-trip':<12}{rt:>10.1f}ms{ROUND_TRIP_TARGET_MS:>8.1f}ms{verdict:>9}")
    print("  (network counted x2: caller->server + server->caller)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch AI latency report")
    parser.add_argument("--turns", type=int, default=3, help="round trips to measure")
    parser.add_argument(
        "--real", action="store_true",
        help="use live providers via the factory (PROVIDER_MODE=real + keys)",
    )
    args = parser.parse_args()
    tracker = asyncio.run(run_report(turns=args.turns, real=args.real))
    _print_table(tracker, real=args.real)


if __name__ == "__main__":
    main()
