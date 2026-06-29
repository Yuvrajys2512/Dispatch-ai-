"""FastAPI application entrypoint for Dispatch AI."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.analytics.router import router as analytics_router
from app.config import ProviderMode, settings
from app.demo.router import router as demo_router
from app.logging_config import configure_logging
from app.realtime.router import router as realtime_router

logger = logging.getLogger("dispatch.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Switch to structured JSON logs as soon as the server starts.
    configure_logging(settings.log_level)
    logger.info("dispatch-ai starting", extra={"provider_mode": settings.provider_mode.value})
    # Startup: in real mode, launch the Exotel intake loop as a background task.
    # _intake is set below at module load when PROVIDER_MODE=real; unreachable in
    # mock mode so the NameError path is never hit.
    if settings.provider_mode is ProviderMode.REAL:
        logger.info("starting Exotel intake loop (PROVIDER_MODE=real)")
        asyncio.create_task(_intake.run())  # type: ignore[name-defined]
    yield
    # Shutdown: the intake task ends with the process; no explicit cleanup needed.


app = FastAPI(
    title="Dispatch AI",
    description="AI-powered emergency call triage for India's 112 infrastructure.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Realtime: WebSocket event stream + take-over trigger (Phase 4).
app.include_router(realtime_router)
# Analytics: day-level ops numbers for the dashboard footer (Phase 6).
app.include_router(analytics_router)
# Demo: HTTP trigger to fire simulated calls on the deployed backend.
app.include_router(demo_router)


# Real-provider intake (Phase 7): in PROVIDER_MODE=real, mount the Exotel
# webhook + media-WebSocket. The intake loop is launched in the lifespan above.
# Mock mode is untouched — the simulator stays the demo/test driver.
if settings.provider_mode is ProviderMode.REAL:
    from app.adapters.exotel.intake import ExotelIntake, build_intake_router
    from app.adapters.factory import (
        get_asr_provider,
        get_llm_provider,
        get_telephony_provider,
        get_tts_provider,
    )
    from app.agent.triage import TriageAgent

    _telephony = get_telephony_provider()
    _intake = ExotelIntake(
        telephony=_telephony,  # type: ignore[arg-type]
        asr=get_asr_provider(),
        tts=get_tts_provider(),
        agent=TriageAgent(get_llm_provider()),
    )
    app.include_router(build_intake_router(_intake, _telephony))  # type: ignore[arg-type]


@app.get("/health")
def health() -> dict:
    """Liveness probe. Reports provider mode so the dashboard can show it."""
    return {
        "status": "ok",
        "service": "dispatch-ai",
        "version": __version__,
        "provider_mode": settings.provider_mode.value,
    }


@app.get("/")
def root() -> dict:
    return {"service": "dispatch-ai", "docs": "/docs", "health": "/health"}
