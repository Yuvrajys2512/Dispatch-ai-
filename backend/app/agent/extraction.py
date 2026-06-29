"""Extraction layer — structured fields via the LLMProvider, on top of rules.

The agent gets its *draft* incident card from the :class:`LLMProvider.extract`
contract (the mock today, a real model in Phase 7). But severity and confidence
are then overwritten by the agent's own classifier — the LLM is trusted for the
"what was said" fields (incident type, people, needs, summary), never for the
safety-critical decision. This module also adds a tiny location heuristic the
mock LLM doesn't provide, so the card has a place to show on the dashboard.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.adapters.base import LLMProvider
from app.agent.signals import CallerTurn
from app.domain.models import IncidentCard

# Landmark / address cues — if a turn carries one, treat it as the location.
_LOCATION_RE = re.compile(
    r"\b(sector|nagar|colony|road|marg|chowk|chauraha|nh-?\d+|highway|toll|"
    r"metro|station|mall|market|mandi|gali|block|near|paas|ke paas|के पास|"
    r"flyover|circle|bypass|village|gaon|thana|hospital|school)\b",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"\b(?:mera naam|my name is|naam hai|main)\s+([A-Z][a-z]+|\w+)\b",
    re.IGNORECASE,
)


def extract_location(turns: Sequence[CallerTurn]) -> str | None:
    """Return the first caller turn that reads like a place, else None."""
    for t in turns:
        text = t.text.strip()
        if text and _LOCATION_RE.search(text):
            return text
    return None


def extract_caller_name(turns: Sequence[CallerTurn]) -> str | None:
    for t in turns:
        m = _NAME_RE.search(t.text)
        if m:
            cand = m.group(1).strip()
            if cand and cand.lower() not in {"hoon", "hu", "kahaan", "kahan"}:
                return cand
    return None


async def extract_card(llm: LLMProvider, transcript_text: str) -> IncidentCard:
    """Ask the LLM provider for a draft card from the full transcript text."""
    return await llm.extract(transcript_text, IncidentCard)
