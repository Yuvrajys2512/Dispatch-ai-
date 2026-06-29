"""Application settings, environment-driven.

Defaults to `mock` provider mode so the entire system runs with zero external
credentials. Real providers (Exotel/Sarvam/LLM) are wired in Phase 7 by setting
PROVIDER_MODE=real and supplying the relevant keys.
"""

from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderMode(str, Enum):
    MOCK = "mock"
    REAL = "real"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provider selection
    provider_mode: ProviderMode = ProviderMode.MOCK

    # Server
    host: str = "0.0.0.0"
    port: int = 8001
    log_level: str = "info"

    # CORS (comma-separated list in env)
    cors_origins: str = "http://localhost:5173"

    # Dashboard auth: when non-empty, all /api/* and /ws/* endpoints require
    # `Authorization: Bearer <key>` (REST) or `?key=<key>` (WebSocket, since
    # the browser WS API cannot send custom headers). Empty = no auth (local dev
    # and the full test suite, which never sets this).
    dispatch_api_key: str = ""

    # Data layer (used from Phase 1)
    database_url: str = "postgresql+psycopg://dispatch:dispatch@localhost:5433/dispatch"
    redis_url: str = "redis://localhost:6380/0"

    # --- Real provider config (Phase 7) ---
    # Secrets live only in .env (gitignored); .env.example documents placeholders.

    # Exotel telephony (Indian inbound number → webhook → media WebSocket).
    exotel_sid: str = ""
    exotel_token: str = ""
    exotel_api_base: str = "https://api.exotel.com"
    # Operator/desk number a mid-call bridge dials when the AI hands off.
    exotel_operator_number: str = ""
    # Publicly-reachable base URL Exotel calls back (tunnel/deploy). Documented
    # in the runbook; not needed for the credential-free test suite.
    exotel_webhook_base_url: str = ""
    # Toggle call recording on the bridged/answered leg.
    exotel_record: bool = True

    # Sarvam ASR/TTS (Hindi/Indic speech).
    sarvam_api_key: str = ""
    sarvam_api_base: str = "https://api.sarvam.ai"
    sarvam_language: str = "hi-IN"
    sarvam_asr_model: str = "saarika:v2"
    sarvam_tts_model: str = "bulbul:v2"
    sarvam_tts_speaker: str = "meera"

    # Real LLM — the cheap, fast field-extraction witness. Defaults to Claude
    # Haiku 4.5 (the agent never trusts the LLM for severity, so cheap+fast wins).
    llm_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    # Optional base-url override (proxy / gateway); blank = Anthropic default.
    llm_base_url: str = ""

    # --- Resilience (circuit breaker + fallback) ---
    # Per-call timeout before a real provider call is considered failed.
    provider_timeout_ms: int = 1200
    # Consecutive failures that trip the breaker open.
    breaker_failure_threshold: int = 3
    # Seconds the breaker stays open before a trial (half-open) call.
    breaker_reset_seconds: float = 30.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
