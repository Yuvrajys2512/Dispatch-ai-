"""Sarvam TTS adapter — text in, a stream of audio frames out (fast first byte).

Honors :class:`~app.adapters.base.TTSProvider`. Sarvam's TTS endpoint returns the
full synthesized clip (base64), so we emit it as a stream of fixed-size frames with
a deliberately **fast first byte** (the first frame goes out immediately) then the
rest — mirroring a streaming TTS's shape so the orchestrator can start playing audio
to the caller before the whole clip is in hand.

The ``httpx.AsyncClient`` is injected, so the contract tests drive a mocked HTTP
transport (no network, no key).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator

import httpx

from app.adapters.base import AudioChunk

logger = logging.getLogger("dispatch.sarvam.tts")

# Frame size of the emitted audio stream and per-frame pacing (ms). The first
# frame is emitted with minimal delay — the streaming "fast first byte".
FRAME_BYTES = 2048
FIRST_BYTE_DELAY_MS = 2
FRAME_DELAY_MS = 3


def _frame(raw: bytes) -> list[bytes]:
    if not raw:
        return []
    return [raw[i : i + FRAME_BYTES] for i in range(0, len(raw), FRAME_BYTES)]


class SarvamTTSProvider:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        model: str,
        speaker: str,
        language: str,
    ) -> None:
        self._client = client
        self._model = model
        self._speaker = speaker
        self._language = language

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        text = text.strip()
        if not text:
            return
        logger.info("TTS synthesize: %s", text)
        resp = await self._client.post(
            "/text-to-speech",
            json={
                "text": text,
                "model": self._model,
                "speaker": self._speaker,
                "target_language_code": self._language,
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        audios = payload.get("audios") or []
        raw = base64.b64decode(audios[0]) if audios else b""

        frames = _frame(raw)
        t_ms = 0
        for i, frame in enumerate(frames):
            delay = FIRST_BYTE_DELAY_MS if i == 0 else FRAME_DELAY_MS
            await asyncio.sleep(delay / 1000)
            t_ms += delay
            yield AudioChunk(
                payload=frame, seq=i, t_ms=t_ms, is_last=(i == len(frames) - 1)
            )


def build_sarvam_tts(
    *, api_key: str, api_base: str, language: str, model: str, speaker: str
) -> SarvamTTSProvider:
    client = httpx.AsyncClient(
        base_url=api_base,
        headers={"api-subscription-key": api_key},
        timeout=httpx.Timeout(10.0),
    )
    return SarvamTTSProvider(client, model=model, speaker=speaker, language=language)
