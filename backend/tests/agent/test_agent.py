"""TriageAgent — end-to-end pipeline behaviour over the mock LLM."""

import pytest

from app.adapters.mock.llm import MockLLMProvider
from app.agent import TriageAgent
from app.agent.signals import CallerContext
from app.domain.enums import CallState, IncidentType, RouteTarget, Severity
from tests.agent.helpers import turns_of


@pytest.fixture
def agent() -> TriageAgent:
    return TriageAgent(MockLLMProvider())


@pytest.mark.asyncio
async def test_accident_produces_critical_card_and_immediate_route(agent):
    out = await agent.triage(
        turns_of(
            "Accident ho gaya, do log ghayal hain, khoon nikal raha hai",
            "NH-24 Ghaziabad toll plaza ke paas",
        )
    )
    assert out.severity is Severity.CRITICAL
    assert out.card.incident_type is IncidentType.ACCIDENT
    assert out.card.needs_ambulance is True
    assert out.card.people_involved == 2
    assert out.card.location_text == "NH-24 Ghaziabad toll plaza ke paas"
    assert out.route.target is RouteTarget.OPERATOR_IMMEDIATE
    assert out.route.handoff is True
    assert out.final_state is CallState.ROUTED


@pytest.mark.asyncio
async def test_theft_queues_without_handoff(agent):
    out = await agent.triage(
        turns_of("Mera phone chori ho gaya", "Sector 62 Noida metro ke paas")
    )
    assert out.severity is Severity.MEDIUM
    assert out.route.target is RouteTarget.OPERATOR_QUEUE
    assert out.route.handoff is False


@pytest.mark.asyncio
async def test_confident_junk_auto_resolves(agent):
    out = await agent.triage(turns_of("hahaha hello timepass", "arre kuch nahi timepass"))
    assert out.severity is Severity.JUNK
    assert out.route.target is RouteTarget.AUTO_RESOLVE
    assert out.final_state is CallState.RESOLVED


@pytest.mark.asyncio
async def test_card_carries_reasons_and_junk_diagnostics(agent):
    out = await agent.triage(turns_of("Accident ho gaya khoon"))
    assert out.card.details["severity_reasons"]
    assert "junk_probability" in out.card.details


@pytest.mark.asyncio
async def test_agent_is_deterministic(agent):
    a = await agent.triage(turns_of("Accident ho gaya khoon do log ghayal"))
    b = await agent.triage(turns_of("Accident ho gaya khoon do log ghayal"))
    assert a.card.model_dump() == b.card.model_dump()
    assert a.route.target is b.route.target


@pytest.mark.asyncio
async def test_severity_decision_ignores_dumb_llm_guess(agent):
    # The mock LLM would call a laughter-masked accident "JUNK"; the agent's own
    # classifier must still surface CRITICAL (it owns the safety decision).
    out = await agent.triage(turns_of("hahaha accident ho gaya khoon bachao", conf=0.6))
    assert out.severity is Severity.CRITICAL
    assert out.route.handoff is True


@pytest.mark.asyncio
async def test_flagged_prank_caller_with_real_emergency_still_escalates(agent):
    out = await agent.triage(
        turns_of("accident ho gaya bachao do log ghayal", conf=0.7),
        caller=CallerContext(calls_today=4, flagged_prank=True),
    )
    assert out.severity is Severity.CRITICAL
    assert out.route.target is RouteTarget.OPERATOR_IMMEDIATE


@pytest.mark.asyncio
async def test_dialogue_runs_greeting_to_route(agent):
    out = await agent.triage(turns_of("Accident", "Sector 62 ke paas", "do log"))
    assert out.dialogue[0].state is CallState.GREETING
    assert out.dialogue[-1].state is CallState.ROUTE
