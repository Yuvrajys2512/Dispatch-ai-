"""Shared helpers for agent tests."""

from __future__ import annotations

from collections.abc import Sequence

from app.adapters.mock.scenarios import Scenario
from app.agent.signals import CallerContext, CallerTurn, build_signals


def turns_of(*texts: str, conf: float = 0.9) -> list[CallerTurn]:
    """Build caller turns from plain strings (uniform confidence)."""
    return [CallerTurn(text=t, confidence=conf) for t in texts]


def signals_for(*texts: str, conf: float = 0.9, caller: CallerContext | None = None):
    return build_signals(turns_of(*texts, conf=conf), caller=caller)


def scenario_turns(scenario: Scenario) -> list[CallerTurn]:
    return [CallerTurn(t.text, t.confidence, t.silent) for t in scenario.turns]


def scenario_caller(scenario: Scenario) -> CallerContext:
    return CallerContext(
        calls_today=scenario.caller_calls_today,
        is_blacklisted=scenario.caller_blacklisted,
        flagged_prank=scenario.caller_flagged_prank,
    )


def as_text(turns: Sequence[CallerTurn]) -> str:
    return " ".join(t.text for t in turns)
