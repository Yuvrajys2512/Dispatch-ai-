"""Circuit breakers + fallback-to-mock for the real providers (Phase 7).

A real provider reaches the public internet, so it can be slow, flaky, or down.
None of that may ever strand a 112 caller. So every real provider call is wrapped
with:

* a **timeout** (``provider_timeout_ms``) — a hung request is a failure, not a wait;
* a **circuit breaker** — after ``breaker_failure_threshold`` consecutive failures
  the breaker opens for ``breaker_reset_seconds`` and we stop hammering a dead
  provider, then try one trial (half-open) call;
* a **fallback** — on failure or open breaker we fall back to the credential-free
  **mock** provider (LLM/ASR/TTS), so the pipeline keeps producing transcripts,
  cards, and speech. For the safety-critical decision the agent still owns
  severity, and a fatal ASR fault still routes the caller to a human (the
  orchestrator's existing ASR-failure exit) — a provider outage never silently
  drops a real emergency.

The wrappers below satisfy the same :mod:`~app.adapters.base` protocols, so nothing
above the adapter layer can tell a resilient provider from a bare one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from time import perf_counter

from app.adapters.base import (
    ASRProvider,
    AudioChunk,
    ExtractT,
    LLMProvider,
    TranscriptChunk,
    TTSProvider,
)

logger = logging.getLogger("dispatch.resilience")


class CircuitBreaker:
    """A minimal consecutive-failure breaker with a half-open trial window."""

    def __init__(
        self, *, failure_threshold: int, reset_seconds: float, name: str = "provider"
    ) -> None:
        self.failure_threshold = max(1, failure_threshold)
        self.reset_seconds = reset_seconds
        self.name = name
        self._failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        """True if a call may go to the primary (closed, or half-open trial)."""
        if self._opened_at is None:
            return True
        if (perf_counter() - self._opened_at) >= self.reset_seconds:
            return True  # half-open: allow a single trial call
        return False

    @property
    def is_open(self) -> bool:
        return not self.allow()

    def record_success(self) -> None:
        if self._opened_at is not None:
            logger.info("breaker %s closed after a successful trial", self.name)
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold and self._opened_at is None:
            self._opened_at = perf_counter()
            logger.warning(
                "breaker %s OPEN after %d consecutive failures", self.name, self._failures
            )
        elif self._opened_at is not None:
            # A failed trial re-opens the window.
            self._opened_at = perf_counter()


class _BreakerOpen(Exception):
    def __init__(self, label: str) -> None:
        super().__init__(f"{label} circuit breaker open")


@dataclass
class _Resilient:
    """Shared timeout/breaker plumbing for a wrapped provider."""

    breaker: CircuitBreaker
    timeout_s: float
    label: str = "provider"

    async def _guarded(self, coro_factory):
        """Run the primary under timeout+breaker; raise on failure/open breaker."""
        if not self.breaker.allow():
            raise _BreakerOpen(self.label)
        try:
            result = await asyncio.wait_for(coro_factory(), self.timeout_s)
        except Exception:  # noqa: BLE001 - any fault counts against the breaker
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return result


# --- LLM -----------------------------------------------------------------

@dataclass
class ResilientLLMProvider(_Resilient):
    real: LLMProvider = field(default=None)  # type: ignore[assignment]
    fallback: LLMProvider = field(default=None)  # type: ignore[assignment]
    label: str = "llm"

    async def extract(self, prompt: str, schema: type[ExtractT]) -> ExtractT:
        try:
            return await self._guarded(lambda: self.real.extract(prompt, schema))
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm.extract fell back to mock: %s", exc)
            return await self.fallback.extract(prompt, schema)

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        # generate is not on the safety path; fall back wholesale on first failure.
        if self.breaker.allow():
            try:
                stream = self.real.generate(prompt)
                first = await asyncio.wait_for(stream.__anext__(), self.timeout_s)
            except StopAsyncIteration:
                self.breaker.record_success()
                return
            except Exception as exc:  # noqa: BLE001
                self.breaker.record_failure()
                logger.warning("llm.generate fell back to mock: %s", exc)
            else:
                self.breaker.record_success()
                yield first
                async for token in stream:
                    yield token
                return
        async for token in self.fallback.generate(prompt):
            yield token


# --- ASR -----------------------------------------------------------------

@dataclass
class ResilientASRProvider(_Resilient):
    real: ASRProvider = field(default=None)  # type: ignore[assignment]
    fallback: ASRProvider = field(default=None)  # type: ignore[assignment]
    label: str = "asr"

    async def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[TranscriptChunk]:
        # The audio stream is single-use, so buffer it once and replay to whichever
        # provider serves the utterance — fallback can't re-pull a consumed stream.
        frames = [chunk async for chunk in audio]

        async def _replay() -> AsyncIterator[AudioChunk]:
            for frame in frames:
                yield frame

        if self.breaker.allow():
            try:
                stream = self.real.stream_transcribe(_replay())
                first = await asyncio.wait_for(stream.__anext__(), self.timeout_s)
            except StopAsyncIteration:
                self.breaker.record_success()
                return
            except Exception as exc:  # noqa: BLE001 - pre-first-chunk failure → fallback
                self.breaker.record_failure()
                logger.warning("asr.stream_transcribe fell back to mock: %s", exc)
            else:
                self.breaker.record_success()
                yield first
                # A mid-stream fault here propagates to the orchestrator, whose
                # ASR-failure exit routes the caller to a human (never dropped).
                async for chunk in stream:
                    yield chunk
                return
        async for chunk in self.fallback.stream_transcribe(_replay()):
            yield chunk


# --- TTS -----------------------------------------------------------------

@dataclass
class ResilientTTSProvider(_Resilient):
    real: TTSProvider = field(default=None)  # type: ignore[assignment]
    fallback: TTSProvider = field(default=None)  # type: ignore[assignment]
    label: str = "tts"

    async def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        if self.breaker.allow():
            try:
                stream = self.real.stream_synthesize(text)
                first = await asyncio.wait_for(stream.__anext__(), self.timeout_s)
            except StopAsyncIteration:
                self.breaker.record_success()
                return
            except Exception as exc:  # noqa: BLE001
                self.breaker.record_failure()
                logger.warning("tts.stream_synthesize fell back to mock: %s", exc)
            else:
                self.breaker.record_success()
                yield first
                async for chunk in stream:
                    yield chunk
                return
        async for chunk in self.fallback.stream_synthesize(text):
            yield chunk
