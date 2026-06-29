"""Per-hop latency instrumentation (spec §Latency budget).

The spec's round-trip budget — caller speaks → AI responds — is::

    network (audio→server)   ~100ms
    ASR processes chunk      ~300ms
    LLM / agent turn         ~400ms
    TTS first byte           ~300ms
    network (audio→caller)   ~100ms
    ─────────────────────────────────
    total round-trip        ~1200ms   (target: < 1500ms)

:class:`LatencyTracker` wraps each hop in :func:`time.perf_counter` and, at the
end of a call, logs a table comparing measured-vs-budget for every hop. In mock
mode the numbers are tiny (no real network/models), but the *instrumentation* is
exactly what Phase 7 needs to verify the real pipeline against the budget.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter

logger = logging.getLogger("dispatch.latency")

# Spec §Latency budget, in milliseconds. ``network`` is counted twice (in+out).
BUDGET_MS: dict[str, float] = {
    "network": 100.0,
    "asr": 300.0,
    "llm": 400.0,
    "tts": 300.0,
}
ROUND_TRIP_TARGET_MS = 1500.0


@dataclass
class LatencyTracker:
    """Accumulates per-hop timings across a call and logs the budget table."""

    call_id: str
    samples_ms: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )

    @contextmanager
    def measure(self, hop: str) -> Iterator[None]:
        """Time the wrapped block and record it under ``hop``."""
        start = perf_counter()
        try:
            yield
        finally:
            self.samples_ms[hop].append((perf_counter() - start) * 1000.0)

    def record(self, hop: str, elapsed_ms: float) -> None:
        self.samples_ms[hop].append(elapsed_ms)

    def average_ms(self, hop: str) -> float:
        samples = self.samples_ms.get(hop)
        return sum(samples) / len(samples) if samples else 0.0

    def round_trip_ms(self) -> float:
        """Sum of the average hops on a single round trip (network counted x2)."""
        return (
            2 * self.average_ms("network")
            + self.average_ms("asr")
            + self.average_ms("llm")
            + self.average_ms("tts")
        )

    def log_table(self) -> None:
        """Emit the per-hop measured-vs-budget table for this call."""
        lines = [
            f"latency budget (call {self.call_id}) - avg over "
            f"{max((len(v) for v in self.samples_ms.values()), default=0)} turn(s):",
            f"  {'hop':<10} {'measured':>10} {'budget':>10}",
        ]
        for hop, budget in BUDGET_MS.items():
            lines.append(
                f"  {hop:<10} {self.average_ms(hop):>8.1f}ms {budget:>8.1f}ms"
            )
        rt = self.round_trip_ms()
        verdict = "OK" if rt < ROUND_TRIP_TARGET_MS else "OVER"
        lines.append(
            f"  {'round-trip':<10} {rt:>8.1f}ms {ROUND_TRIP_TARGET_MS:>8.1f}ms [{verdict}]"
        )
        logger.info("\n".join(lines))
