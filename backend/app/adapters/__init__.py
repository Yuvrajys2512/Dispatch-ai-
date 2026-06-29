"""Provider abstraction layer.

Protocols + wire types in ``base``; mock implementations in ``mock``; selection
via ``factory`` (driven by ``PROVIDER_MODE``).
"""

from app.adapters.base import (
    ASRProvider,
    AudioChunk,
    IncomingCall,
    LLMProvider,
    TelephonyProvider,
    TranscriptChunk,
    TTSProvider,
)
from app.adapters.factory import (
    get_asr_provider,
    get_llm_provider,
    get_telephony_provider,
    get_tts_provider,
)

__all__ = [
    "ASRProvider",
    "AudioChunk",
    "IncomingCall",
    "LLMProvider",
    "TTSProvider",
    "TelephonyProvider",
    "TranscriptChunk",
    "get_asr_provider",
    "get_llm_provider",
    "get_telephony_provider",
    "get_tts_provider",
]
