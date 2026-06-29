"""Provider factory — selects implementations from ``PROVIDER_MODE``.

Everything above the adapter layer asks the factory for a provider and gets back
something that satisfies the protocol — never a concrete class. ``mock`` (default)
returns the credential-free mocks; ``real`` (Phase 7) returns the Exotel / Sarvam /
LLM adapters, each (for LLM/ASR/TTS) wrapped with a **circuit breaker + fallback to
the mock** so a provider outage never strands a caller. Swapping mock↔real is a
config flip — no caller changes.
"""

from __future__ import annotations

from app.adapters.base import (
    ASRProvider,
    LLMProvider,
    TelephonyProvider,
    TTSProvider,
)
from app.adapters.mock import (
    MockASRProvider,
    MockLLMProvider,
    MockTelephonyProvider,
    MockTTSProvider,
)
from app.adapters.resilience import (
    CircuitBreaker,
    ResilientASRProvider,
    ResilientLLMProvider,
    ResilientTTSProvider,
)
from app.config import ProviderMode, settings


def _is_mock() -> bool:
    return settings.provider_mode is ProviderMode.MOCK


def _breaker(name: str) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=settings.breaker_failure_threshold,
        reset_seconds=settings.breaker_reset_seconds,
        name=name,
    )


def _timeout_s() -> float:
    return settings.provider_timeout_ms / 1000.0


# The real Exotel telephony provider is a stateful hub (the intake route and the
# media WebSocket share it), so it must be a singleton within the process.
_real_telephony: TelephonyProvider | None = None


def get_telephony_provider() -> TelephonyProvider:
    if _is_mock():
        return MockTelephonyProvider()
    global _real_telephony
    if _real_telephony is None:
        from app.adapters.exotel import build_exotel_telephony

        _real_telephony = build_exotel_telephony(
            sid=settings.exotel_sid,
            token=settings.exotel_token,
            api_base=settings.exotel_api_base,
            operator_number=settings.exotel_operator_number,
            record=settings.exotel_record,
        )
    return _real_telephony


def get_asr_provider() -> ASRProvider:
    if _is_mock():
        return MockASRProvider()
    from app.adapters.sarvam import build_sarvam_asr

    real = build_sarvam_asr(
        api_key=settings.sarvam_api_key,
        api_base=settings.sarvam_api_base,
        language=settings.sarvam_language,
        model=settings.sarvam_asr_model,
    )
    return ResilientASRProvider(
        breaker=_breaker("sarvam-asr"),
        timeout_s=_timeout_s(),
        real=real,
        fallback=MockASRProvider(),
    )


def get_tts_provider() -> TTSProvider:
    if _is_mock():
        return MockTTSProvider()
    from app.adapters.sarvam import build_sarvam_tts

    real = build_sarvam_tts(
        api_key=settings.sarvam_api_key,
        api_base=settings.sarvam_api_base,
        language=settings.sarvam_language,
        model=settings.sarvam_tts_model,
        speaker=settings.sarvam_tts_speaker,
    )
    return ResilientTTSProvider(
        breaker=_breaker("sarvam-tts"),
        timeout_s=_timeout_s(),
        real=real,
        fallback=MockTTSProvider(),
    )


def get_llm_provider() -> LLMProvider:
    if _is_mock():
        return MockLLMProvider()
    from app.adapters.llm import build_anthropic_llm

    real = build_anthropic_llm(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
    )
    return ResilientLLMProvider(
        breaker=_breaker("llm"),
        timeout_s=_timeout_s(),
        real=real,
        fallback=MockLLMProvider(),
    )


def reset_real_providers() -> None:
    """Drop the cached real telephony singleton (tests / reconfiguration)."""
    global _real_telephony
    _real_telephony = None
