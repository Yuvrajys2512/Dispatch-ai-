"""WebSocket event hub — a tiny in-process publish/subscribe fan-out.

The orchestrator publishes :class:`~app.realtime.events.Event` objects; every
subscriber (a dashboard WebSocket client, a test, the simulator's console
printer) gets its own :class:`asyncio.Queue` and receives a copy. The hub is
deliberately infrastructure-free — no Redis pub/sub, no broker — because a single
backend process owns all live call sessions in this phase. Phase 8 can swap this
for a cross-process bus without touching publishers or subscribers.

Back-pressure policy: a slow subscriber whose queue fills up **drops** events
rather than blocking the call pipeline (a stalled dashboard must never slow down
triage). The ``seq`` on each event lets a client detect such a gap.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.realtime.events import Event

logger = logging.getLogger("dispatch.hub")

# Per-subscriber buffer. Large enough that a whole call's events fit even if a
# client is briefly slow; overflow drops oldest-not-read rather than blocking.
DEFAULT_QUEUE_SIZE = 10_000


class EventHub:
    """Fan-out registry of subscriber queues."""

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[Event]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        """Register a subscriber for the lifetime of the ``async with`` block."""
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def publish(self, event: Event) -> None:
        """Deliver ``event`` to every current subscriber (non-blocking)."""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - slow-consumer guard
                logger.warning(
                    "subscriber queue full; dropping %s (call %s seq %s)",
                    event.type,
                    event.call_id,
                    event.seq,
                )


# Process-wide default hub shared by the simulator and the WebSocket endpoint.
default_hub = EventHub()
