"""Demo trigger endpoint — starts simulated calls on the live backend.

``POST /api/demo/run`` fires the default 6 archetype scenarios through the
real pipeline so the Vercel dashboard shows live calls without needing Exotel.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.adapters.mock.scenarios import DEFAULT_SCENARIO_IDS, TRIAGE_CORPUS
from app.simulator.runner import simulate

logger = logging.getLogger("dispatch.demo")

router = APIRouter(prefix="/api/demo", tags=["demo"])

_running = False


@router.post("/run")
async def run_demo(background_tasks: BackgroundTasks, scenario_set: str = "default") -> dict:
    """Fire a batch of simulated calls through the live pipeline.

    - ``scenario_set=default`` — the 6 archetype calls (fire, cardiac, accident,
      domestic assault, junk prank, junk accidental).
    - ``scenario_set=all`` — the full 58-scenario corpus (takes ~30 s).
    """
    global _running
    if _running:
        raise HTTPException(status_code=409, detail="A demo batch is already running.")

    ids = DEFAULT_SCENARIO_IDS if scenario_set != "all" else tuple(s.id for s in TRIAGE_CORPUS[:10])

    async def _run() -> None:
        global _running
        _running = True
        try:
            calls = await simulate(ids, concurrency=3)
            logger.info("demo batch complete: %d calls", len(calls))
        except Exception:
            logger.exception("demo batch failed")
        finally:
            _running = False

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "scenarios": len(ids),
        "message": f"Running {len(ids)} simulated calls — watch the dashboard.",
    }


@router.get("/status")
async def demo_status() -> dict:
    """Returns whether a demo batch is currently running."""
    return {"running": _running}
