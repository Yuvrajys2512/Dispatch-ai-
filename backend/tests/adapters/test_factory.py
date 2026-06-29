"""Factory contract: PROVIDER_MODE selects implementations (mock + real)."""

import pytest

from app.adapters import base, factory
from app.adapters.mock import (
    MockASRProvider,
    MockLLMProvider,
    MockTelephonyProvider,
    MockTTSProvider,
)
from app.adapters.resilience import (
    ResilientASRProvider,
    ResilientLLMProvider,
    ResilientTTSProvider,
)
from app.config import ProviderMode


def test_mock_mode_returns_protocol_satisfying_providers():
    assert isinstance(factory.get_telephony_provider(), base.TelephonyProvider)
    assert isinstance(factory.get_asr_provider(), base.ASRProvider)
    assert isinstance(factory.get_tts_provider(), base.TTSProvider)
    assert isinstance(factory.get_llm_provider(), base.LLMProvider)
    # Mock mode returns the bare mocks (no resilience wrapper).
    assert isinstance(factory.get_asr_provider(), MockASRProvider)
    assert isinstance(factory.get_llm_provider(), MockLLMProvider)


@pytest.fixture
def real_mode(monkeypatch):
    """Switch the factory to real mode with placeholder (non-network) keys."""
    monkeypatch.setattr(factory.settings, "provider_mode", ProviderMode.REAL)
    for field, value in {
        "exotel_sid": "sid",
        "exotel_token": "tok",
        "sarvam_api_key": "skey",
        "llm_api_key": "lkey",
    }.items():
        monkeypatch.setattr(factory.settings, field, value)
    factory.reset_real_providers()
    yield
    factory.reset_real_providers()


def test_real_mode_returns_protocol_satisfying_providers(real_mode):
    # Every real provider still satisfies the exact same protocol — no caller change.
    assert isinstance(factory.get_telephony_provider(), base.TelephonyProvider)
    assert isinstance(factory.get_asr_provider(), base.ASRProvider)
    assert isinstance(factory.get_tts_provider(), base.TTSProvider)
    assert isinstance(factory.get_llm_provider(), base.LLMProvider)


def test_real_mode_wraps_with_resilience_and_mock_fallback(real_mode):
    asr = factory.get_asr_provider()
    tts = factory.get_tts_provider()
    llm = factory.get_llm_provider()
    assert isinstance(asr, ResilientASRProvider)
    assert isinstance(tts, ResilientTTSProvider)
    assert isinstance(llm, ResilientLLMProvider)
    # The breaker falls back to the credential-free mock — never strands a caller.
    assert isinstance(asr.fallback, MockASRProvider)
    assert isinstance(tts.fallback, MockTTSProvider)
    assert isinstance(llm.fallback, MockLLMProvider)


def test_real_telephony_is_a_singleton(real_mode):
    # The Exotel hub is shared by the intake loop and the media WebSocket.
    assert factory.get_telephony_provider() is factory.get_telephony_provider()


def test_mock_mode_telephony_is_not_the_real_singleton():
    assert isinstance(factory.get_telephony_provider(), MockTelephonyProvider)
