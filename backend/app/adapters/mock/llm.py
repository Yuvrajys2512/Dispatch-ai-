"""Mock LLM provider — deterministic, rule-based, no API key needed.

Honors :class:`~app.adapters.base.LLMProvider`. ``extract`` runs a small
keyword rule-engine over the (Hindi/Hinglish/English) text and returns a
populated instance of whatever Pydantic ``schema`` is requested, relying on the
schema's defaults for fields it can't infer. ``generate`` streams a scripted,
calm response token-by-token.

This is intentionally *mock-grade*: it makes the conversation agent (Phase 3)
fully testable with zero credentials. The real severity classifier and the real
LLM adapter arrive in Phases 3 and 7; both must pass the same contract tests.
Emitted enum values are plain strings (e.g. ``"CRITICAL"``) so this module stays
decoupled from the domain package — Pydantic coerces them on validation.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator

from app.adapters.base import ExtractT

GEN_TOKEN_DELAY_MS = 3

# Keyword signals (Hindi / Hinglish / English).
_CRITICAL = (
    "accident", "blood", "khoon", "fire", "aag", "unconscious", "behosh",
    "trapped", "gun", "knife", "chaaku", "bachao", "madad", "saans",
    "breathing", "ghayal", "injured",
)
_HIGH = ("dard", "chest pain", "seene", "seizure", "robbery", "loot", "assault", "maar")
_THEFT = ("chori", "theft", "stolen", "snatch", "phone chori")
_JUNK = ("haha", "*laughing*", "timepass", "wrong number", "galat number")

_HINDI_NUMS = {"ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5}


def _contains(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _people_involved(text: str) -> int | None:
    m = re.search(r"\b(\d+)\b", text)
    if m:
        return int(m.group(1))
    for word, n in _HINDI_NUMS.items():
        if re.search(rf"\b{word}\b", text):
            return n
    return None


class MockLLMProvider:
    def _derive(self, prompt: str) -> dict[str, object]:
        t = prompt.lower()
        data: dict[str, object] = {}

        # Severity + incident type.
        if _contains(t, _JUNK) or not t.strip():
            data["severity"] = "JUNK"
            data["confidence"] = 0.9
        elif _contains(t, _CRITICAL):
            data["severity"] = "CRITICAL"
            data["confidence"] = 0.9
        elif _contains(t, _HIGH):
            data["severity"] = "HIGH"
            data["confidence"] = 0.85
        elif _contains(t, _THEFT):
            data["severity"] = "MEDIUM"
            data["confidence"] = 0.8
        else:
            data["severity"] = "LOW"
            data["confidence"] = 0.6

        if "accident" in t:
            data["incident_type"] = "ACCIDENT"
        elif _contains(t, ("fire", "aag")):
            data["incident_type"] = "FIRE"
        elif _contains(t, _THEFT):
            data["incident_type"] = "THEFT"
        elif _contains(t, ("dard", "seene", "saans", "behosh", "medical")):
            data["incident_type"] = "MEDICAL"
        elif _contains(t, ("maar", "assault", "loot", "robbery")):
            data["incident_type"] = "ASSAULT"
        else:
            data["incident_type"] = "OTHER" if t.strip() else "UNKNOWN"

        # Service needs.
        data["needs_ambulance"] = _contains(
            t, ("ghayal", "injured", "khoon", "blood", "dard", "saans", "behosh")
        )
        data["needs_fire"] = _contains(t, ("fire", "aag"))
        data["needs_police"] = _contains(t, _THEFT + ("accident", "loot", "assault", "maar"))

        people = _people_involved(t)
        if people is not None:
            data["people_involved"] = people

        data["summary"] = prompt.strip()[:280]
        return data

    async def extract(self, prompt: str, schema: type[ExtractT]) -> ExtractT:
        derived = self._derive(prompt)
        fields = schema.model_fields
        data = {k: v for k, v in derived.items() if k in fields}
        return schema.model_validate(data)

    async def generate(self, prompt: str) -> AsyncIterator[str]:
        response = self._response_for(prompt)
        for i, token in enumerate(response.split()):
            await asyncio.sleep(GEN_TOKEN_DELAY_MS / 1000)
            yield token if i == 0 else f" {token}"

    @staticmethod
    def _response_for(prompt: str) -> str:
        t = prompt.lower()
        if not t.strip():
            return "112 emergency. Kya hua? Aap kahaan hain?"
        if _contains(t, _CRITICAL) or _contains(t, _HIGH):
            return (
                "Main aapki location pe turant madad bhej raha hoon. "
                "Aap line pe baney rahiye, ghabraaiye mat."
            )
        if _contains(t, _THEFT):
            return (
                "Theek hai, main aapki shikayat darj kar raha hoon. "
                "Aap surakshit jagah par rahiye."
            )
        if _contains(t, _JUNK):
            return "Yeh emergency line hai. Agar aapko madad chahiye to bataaiye."
        return "Theek hai, main samajh gaya. Aur kuch bataana chahenge?"
