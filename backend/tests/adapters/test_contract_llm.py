"""LLM contract: structured extraction + streamed generation.

Run against **both** the mock and the real Anthropic adapter (real with a mocked
HTTP transport that replays the mock's deterministic rule engine). The real adapter
passes the identical assertions — that is the contract-parity release gate.
"""

import pytest

from app.adapters.base import LLMProvider
from app.adapters.mock.llm import MockLLMProvider
from app.domain.enums import IncidentType, Severity
from app.domain.models import IncidentCard
from tests.adapters.helpers import collect
from tests.adapters.realfakes import make_anthropic_provider


@pytest.fixture(params=["mock", "real"])
def llm(request) -> LLMProvider:
    return MockLLMProvider() if request.param == "mock" else make_anthropic_provider()


def test_provider_satisfies_protocol(llm):
    assert isinstance(llm, LLMProvider)


@pytest.mark.asyncio
async def test_extract_returns_populated_schema_instance(llm):
    card = await llm.extract(
        "Accident ho gaya, do log ghayal hain, khoon nikal raha hai", IncidentCard
    )
    assert isinstance(card, IncidentCard)
    assert card.severity is Severity.CRITICAL
    assert card.incident_type is IncidentType.ACCIDENT
    assert card.needs_ambulance is True
    assert card.people_involved == 2
    assert 0.0 <= card.confidence <= 1.0


@pytest.mark.asyncio
async def test_extract_classifies_junk_and_theft(llm):
    junk = await llm.extract("hahaha timepass *laughing*", IncidentCard)
    assert junk.severity is Severity.JUNK

    theft = await llm.extract("Mera phone chori ho gaya", IncidentCard)
    assert theft.severity is Severity.MEDIUM
    assert theft.incident_type is IncidentType.THEFT


@pytest.mark.asyncio
async def test_extract_is_deterministic(llm):
    a = await llm.extract("seene mein dard ho raha hai", IncidentCard)
    b = await llm.extract("seene mein dard ho raha hai", IncidentCard)
    assert a.model_dump() == b.model_dump()
    assert a.severity is Severity.HIGH


@pytest.mark.asyncio
async def test_generate_streams_nonempty_tokens(llm):
    tokens = await collect(llm.generate("accident ho gaya"))
    assert len(tokens) > 1
    text = "".join(tokens)
    assert text.strip()
    tokens2 = await collect(llm.generate("accident ho gaya"))
    assert "".join(tokens2) == text


@pytest.mark.asyncio
async def test_generate_greets_on_empty_prompt(llm):
    text = "".join(await collect(llm.generate("")))
    assert "112" in text
