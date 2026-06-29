"""Triage state machine — GREETING → … → ROUTE, with re-ask/clarify.

The LLM handles the messy understanding; this machine owns the *flow* (spec §3).
It walks a call through the fixed sequence of states, asking for the one thing
each state needs and **re-asking once** (clarify) when the caller's answer didn't
carry it — then moving on rather than getting stuck. It is a pure, deterministic
driver: feed it caller turns, get back the ordered (state, AI line) dialogue and
the terminal state. The orchestrator ( :mod:`app.agent.triage` ) pairs it with
the classifiers to fill the card as the states advance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.agent import extraction
from app.agent.prompts import prompt_for
from app.agent.signals import CallerTurn
from app.domain.enums import CallState

MAX_CLARIFY = 1


@dataclass(frozen=True)
class DialogueStep:
    """One AI turn: the state it was spoken from and the line said."""

    state: CallState
    ai_line: str
    clarify: bool = False


@dataclass
class _Knowledge:
    """What the machine has gathered so far (drives satisfied/clarify checks)."""

    incident_known: bool = False
    location_known: bool = False
    details_known: bool = False
    spoken: list[str] = field(default_factory=list)


def _satisfied(state: CallState, k: _Knowledge) -> bool:
    if state is CallState.INCIDENT_TYPE:
        return k.incident_known
    if state is CallState.LOCATION:
        return k.location_known
    if state is CallState.DETAILS:
        return k.details_known
    return True


def _ingest(turn: CallerTurn, k: _Knowledge) -> None:
    """Fold one caller turn into the running knowledge."""
    from app.agent.keywords import (
        CRITICAL_RE,
        DOMESTIC_RE,
        HIGH_RE,
        INFO_RE,
        THEFT_RE,
        has,
    )

    if turn.silent or not turn.text.strip():
        return
    k.spoken.append(turn.text)
    low = turn.text.lower()
    if any(has(low, r) for r in (CRITICAL_RE, HIGH_RE, THEFT_RE, DOMESTIC_RE, INFO_RE)):
        k.incident_known = True
    if extraction.extract_location([turn]) is not None:
        k.location_known = True
    if any(c.isdigit() for c in low) or any(
        w in low for w in ("ghayal", "injured", "ambulance", "police", "log", "koi nahi")
    ):
        k.details_known = True


# The information-gathering states, in order (each asks for one thing).
_GATHERING: tuple[CallState, ...] = (
    CallState.INCIDENT_TYPE,
    CallState.LOCATION,
    CallState.DETAILS,
)


class TriageStateMachine:
    """Deterministic flow driver. One instance per call."""

    def __init__(self) -> None:
        self.state: CallState = CallState.GREETING

    def drive(self, turns: Sequence[CallerTurn]) -> list[DialogueStep]:
        """Plan a whole call; return the ordered AI dialogue.

        The machine folds the caller turns into what it learned, then walks the
        fixed flow GREETING → INCIDENT_TYPE → LOCATION → DETAILS →
        SEVERITY_SCORE → ROUTE. Each gathering state asks its question; if that
        piece of information never arrived, it re-asks once (a clarify) before
        moving on so the call can never stall.
        """
        k = _Knowledge()
        for turn in turns:
            _ingest(turn, k)

        steps: list[DialogueStep] = [
            DialogueStep(CallState.GREETING, prompt_for(CallState.GREETING))
        ]
        for state in _GATHERING:
            self.state = state
            steps.append(DialogueStep(state, prompt_for(state)))
            if not _satisfied(state, k):
                for _ in range(MAX_CLARIFY):
                    steps.append(
                        DialogueStep(state, prompt_for(state, clarify=True), clarify=True)
                    )
        self.state = CallState.SEVERITY_SCORE
        steps.append(DialogueStep(self.state, prompt_for(self.state)))
        self.state = CallState.ROUTE
        steps.append(DialogueStep(self.state, prompt_for(self.state)))
        return steps
