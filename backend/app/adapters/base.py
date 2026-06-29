"""Provider abstraction layer — protocols + shared wire types.

Every external dependency (telephony, ASR, TTS, LLM) is reachable only through
one of these ``Protocol`` interfaces. A mock implementation (Phase 2) and a real
implementation (Phase 7) both satisfy the same protocol and must pass the same
contract test suite — so business logic above this layer never changes when we
swap mock for real.

The data types here are deliberately tiny and infrastructure-free; they are the
"wire format" the orchestrator moves between adapters.

### A note on mock "audio"

In ``PROVIDER_MODE=mock`` there is no real audio codec. We use a trivial
synthetic one: an :class:`AudioChunk`'s ``payload`` is just UTF-8 text bytes
(see :meth:`AudioChunk.from_text` / :attr:`AudioChunk.text`). That lets the mock
telephony "speak" scripted caller turns and the mock ASR "hear" them, while the
*shape* of the pipeline (a stream of audio chunks → a stream of transcript
chunks) is identical to the real thing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

# --- Wire types -----------------------------------------------------------

@dataclass(frozen=True)
class IncomingCall:
    """A new call arriving from the telephony layer."""

    call_id: str
    from_number: str
    to_number: str = "112"
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AudioChunk:
    """One frame of streaming audio.

    ``seq`` is the monotonic frame index within a stream; ``t_ms`` is the
    millisecond offset since the stream/utterance started; ``is_last`` marks the
    final frame of an utterance (so ASR knows when to emit a final transcript).
    """

    payload: bytes
    seq: int = 0
    t_ms: int = 0
    is_last: bool = True
    # Out-of-band transport metadata. In mock mode it carries simulation hints
    # (e.g. ``asr_confidence``); real adapters generally leave it empty.
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        text: str,
        *,
        seq: int = 0,
        t_ms: int = 0,
        is_last: bool = True,
        asr_confidence: float | None = None,
    ) -> AudioChunk:
        """Mock-mode helper: encode text as the synthetic 'audio' payload."""
        meta = {} if asr_confidence is None else {"asr_confidence": asr_confidence}
        return cls(
            payload=text.encode("utf-8"), seq=seq, t_ms=t_ms, is_last=is_last, meta=meta
        )

    @property
    def text(self) -> str:
        """Mock-mode helper: decode the synthetic payload back to text."""
        return self.payload.decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class TranscriptChunk:
    """An ASR result. Partial (in-flight) until ``is_final``.

    ``confidence`` is 0–1. Partials typically carry lower confidence than the
    final, and a final's text is the full utterance.
    """

    text: str
    is_final: bool
    confidence: float
    t_ms: int = 0


# --- Protocols ------------------------------------------------------------

ExtractT = TypeVar("ExtractT", bound=BaseModel)


@runtime_checkable
class TelephonyProvider(Protocol):
    """Receives calls, carries bidirectional audio, bridges to an operator."""

    def incoming_calls(self) -> AsyncIterator[IncomingCall]:
        """Stream of new inbound calls."""
        ...

    def caller_audio(self, call_id: str) -> AsyncIterator[AudioChunk]:
        """Inbound audio frames from the caller for ``call_id``."""
        ...

    async def send_audio(self, call_id: str, audio: AudioChunk) -> None:
        """Send an outbound (AI/TTS) audio frame to the caller."""
        ...

    async def bridge_to_operator(self, call_id: str) -> None:
        """Patch a human operator into the live call; the AI drops out."""
        ...

    async def hangup(self, call_id: str) -> None:
        """End the call."""
        ...


@runtime_checkable
class ASRProvider(Protocol):
    """Streaming speech-to-text."""

    def stream_transcribe(
        self, audio: AsyncIterator[AudioChunk]
    ) -> AsyncIterator[TranscriptChunk]:
        """Consume audio frames; yield partial → final transcript chunks."""
        ...


@runtime_checkable
class TTSProvider(Protocol):
    """Streaming text-to-speech."""

    def stream_synthesize(self, text: str) -> AsyncIterator[AudioChunk]:
        """Yield audio frames for ``text`` (first byte fast, then the rest)."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Structured extraction + natural-language generation."""

    async def extract(self, prompt: str, schema: type[ExtractT]) -> ExtractT:
        """Return a ``schema`` instance populated from ``prompt``."""
        ...

    def generate(self, prompt: str) -> AsyncIterator[str]:
        """Stream a natural-language response token-by-token."""
        ...
