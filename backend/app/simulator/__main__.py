"""CLI: drive the simulator and print the live event stream.

Mirrors ``python -m app.db.seed`` in style. It subscribes to the default event
hub, launches a batch of scripted calls through the real orchestrator pipeline
(persisting to PostgreSQL + Redis — ``docker compose up`` first), and prints the
**ordered** WebSocket event stream to stdout as it happens.

Usage::

    python -m app.simulator                          # the 6 default archetypes
    python -m app.simulator accident_injuries silent # named scenarios
    python -m app.simulator --concurrency 5          # up to 5 at once
    python -m app.simulator --schedule 30            # a fresh batch every 30s

Output is deliberately ASCII-only (the Windows console is cp1252).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.adapters.mock.scenarios import DEFAULT_SCENARIO_IDS
from app.realtime.events import Event
from app.realtime.hub import default_hub
from app.simulator.runner import simulate


def _format(event: Event) -> str:
    tag = f"[{event.call_id[:8]} #{event.seq:<2}] {event.type:<18}"
    t = event.type
    if t == "call.started":
        return f"{tag} phone={event.phone} scenario={event.scenario}"
    if t == "transcript.partial":
        return f"{tag} '{event.text}' (~{event.confidence:.2f})"
    if t == "transcript.final":
        return f"{tag} '{event.text}' (conf {event.confidence:.2f})"
    if t == "incident.updated":
        card = event.incident
        return (
            f"{tag} type={card.incident_type.value} sev={card.severity.value} "
            f"conf={card.confidence:.2f} loc={card.location_text or '-'}"
        )
    if t == "severity.changed":
        prev = event.previous.value if event.previous else "-"
        return f"{tag} {prev} -> {event.current.value}"
    if t == "route.decided":
        return (
            f"{tag} {event.target.value} sev={event.severity.value} "
            f"handoff={event.handoff} ({event.reason})"
        )
    if t == "operator.takeover":
        return f"{tag} reason={event.reason}"
    if t == "call.ended":
        return f"{tag} state={event.final_state.value} dur={event.duration_seconds:.2f}s"
    return tag


async def _drain(queue: asyncio.Queue, stop: asyncio.Event) -> None:
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=0.1)
        except TimeoutError:
            if stop.is_set():
                return
            continue
        print(_format(event))


async def _run_batch(scenario_ids: list[str], concurrency: int) -> None:
    stop = asyncio.Event()
    async with default_hub.subscribe() as queue:
        printer = asyncio.create_task(_drain(queue, stop))
        calls = await simulate(scenario_ids, concurrency=concurrency)
        await asyncio.sleep(0.05)  # let the last events flush to the printer
        stop.set()
        await printer

    print("-" * 60)
    for call in calls:
        route = call.route.target.value if call.route else "-"
        print(
            f"  {call.id} state={call.state.value:<12} "
            f"sev={call.incident.severity.value:<8} route={route}"
        )
    print(f"[DONE] {len(calls)} call(s) completed.")


async def main() -> None:
    # The agent's reason strings carry the odd non-ASCII glyph (e.g. "severity ≥
    # HIGH"); the default Windows console is cp1252, so make stdout UTF-8-tolerant
    # rather than crash on a stray character.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Dispatch AI call simulator")
    parser.add_argument(
        "scenarios",
        nargs="*",
        default=list(DEFAULT_SCENARIO_IDS),
        help="scenario ids to run (default: the 6 demo archetypes)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3, help="concurrent calls, 1-5 (default 3)"
    )
    parser.add_argument(
        "--schedule",
        type=float,
        default=None,
        help="if set, run a fresh batch every N seconds (Ctrl+C to stop)",
    )
    args = parser.parse_args()
    scenario_ids = args.scenarios or list(DEFAULT_SCENARIO_IDS)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.schedule is None:
        await _run_batch(scenario_ids, args.concurrency)
        return

    print(f"[SCHEDULE] every {args.schedule}s; Ctrl+C to stop.")
    while True:
        await _run_batch(scenario_ids, args.concurrency)
        await asyncio.sleep(args.schedule)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[STOP] simulator interrupted.")
