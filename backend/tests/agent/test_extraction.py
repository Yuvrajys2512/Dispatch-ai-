"""Extraction layer — LLM-backed draft card + location/name heuristics."""

import pytest

from app.adapters.mock.llm import MockLLMProvider
from app.agent import extraction
from app.domain.models import IncidentCard
from tests.agent.helpers import turns_of


def test_extract_location_picks_a_place_turn():
    turns = turns_of("Accident ho gaya khoon", "Sector 62 Noida metro ke paas")
    assert extraction.extract_location(turns) == "Sector 62 Noida metro ke paas"


def test_extract_location_none_when_absent():
    assert extraction.extract_location(turns_of("Accident ho gaya")) is None


def test_extract_caller_name():
    turns = turns_of("Mera naam Rahul hai", "Accident ho gaya")
    assert extraction.extract_caller_name(turns) == "Rahul"


@pytest.mark.asyncio
async def test_extract_card_uses_llm_provider():
    llm = MockLLMProvider()
    card = await extraction.extract_card(llm, "Accident ho gaya do log ghayal khoon")
    assert isinstance(card, IncidentCard)
    # The draft comes from the LLM contract; the agent overrides severity later.
    assert card.summary
