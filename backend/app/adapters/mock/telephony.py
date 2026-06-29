"""Mock telephony provider — replays scripted scenarios as if they were calls.

Honors :class:`~app.adapters.base.TelephonyProvider`. ``incoming_calls`` emits
one :class:`IncomingCall` per configured scenario; ``caller_audio`` replays that
scenario's turns as synthetic audio frames (one word per frame, ending each
utterance with ``is_last=True``). Outbound audio, bridges, and hangups are
recorded so tests/the dashboard can observe them.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from app.adapters.base import AudioChunk, IncomingCall
from app.adapters.mock.scenarios import (
    DEFAULT_SCENARIO_IDS,
    Scenario,
    get_scenario,
)

# Simulated pacing (kept tiny so tests stay fast while ordering/timing is real).
NEW_CALL_GAP_MS = 5
FRAME_GAP_MS = 2


class MockTelephonyProvider:
    def __init__(self, scenarios: Iterable[Scenario] | None = None) -> None:
        self.scenarios: list[Scenario] = (
            list(scenarios)
            if scenarios is not None
            else [get_scenario(i) for i in DEFAULT_SCENARIO_IDS]
        )
        self._by_call: dict[str, Scenario] = {}
        # Observable side effects, for tests and the orchestrator.
        self.sent_audio: dict[str, list[AudioChunk]] = {}
        self.bridged: set[str] = set()
        self.hung_up: set[str] = set()

    async def incoming_calls(self) -> AsyncIterator[IncomingCall]:
        for scenario in self.scenarios:
            call_id = f"mock-{scenario.id}"
            self._by_call[call_id] = scenario
            self.sent_audio[call_id] = []
            await asyncio.sleep(NEW_CALL_GAP_MS / 1000)
            yield IncomingCall(
                call_id=call_id,
                from_number=scenario.from_number,
                metadata={"scenario": scenario.id, "tags": list(scenario.tags)},
            )

    async def caller_audio(self, call_id: str) -> AsyncIterator[AudioChunk]:
        scenario = self._by_call[call_id]
        t_ms = 0
        for turn in scenario.turns:
            if turn.silent:
                # Dead air: a single empty, low-confidence final frame.
                t_ms += FRAME_GAP_MS
                yield AudioChunk.from_text(
                    "", seq=0, t_ms=t_ms, is_last=True, asr_confidence=turn.confidence
                )
                continue
            words = turn.text.split()
            for i, word in enumerate(words):
                t_ms += FRAME_GAP_MS
                is_last = i == len(words) - 1
                await asyncio.sleep(FRAME_GAP_MS / 1000)
                yield AudioChunk.from_text(
                    word,
                    seq=i,
                    t_ms=t_ms,
                    is_last=is_last,
                    asr_confidence=turn.confidence if is_last else None,
                )

    async def send_audio(self, call_id: str, audio: AudioChunk) -> None:
        self.sent_audio.setdefault(call_id, []).append(audio)

    async def bridge_to_operator(self, call_id: str) -> None:
        self.bridged.add(call_id)

    async def hangup(self, call_id: str) -> None:
        self.hung_up.add(call_id)
