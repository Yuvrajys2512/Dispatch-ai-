"""adapters/sarvam package — real Hindi/Indic ASR + TTS over Sarvam."""

from app.adapters.sarvam.asr import (
    ASRSocket,
    SarvamASRProvider,
    build_sarvam_asr,
)
from app.adapters.sarvam.tts import SarvamTTSProvider, build_sarvam_tts

__all__ = [
    "ASRSocket",
    "SarvamASRProvider",
    "SarvamTTSProvider",
    "build_sarvam_asr",
    "build_sarvam_tts",
]
