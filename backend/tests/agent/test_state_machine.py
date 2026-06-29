"""State machine — flow, ordering, and re-ask/clarify behaviour (spec §3)."""

from app.agent.prompts import CLARIFY, prompt_for
from app.agent.state_machine import MAX_CLARIFY, TriageStateMachine
from app.domain.enums import CallState
from tests.agent.helpers import turns_of


def _states(steps):
    return [s.state for s in steps]


def test_greets_first_and_reaches_route():
    steps = TriageStateMachine().drive(
        turns_of("Accident ho gaya", "NH-24 ke paas", "Do log ghayal")
    )
    assert steps[0].state is CallState.GREETING
    assert steps[-1].state is CallState.ROUTE


def test_flow_advances_in_order_when_info_present():
    steps = TriageStateMachine().drive(
        turns_of(
            "Accident ho gaya khoon",  # incident
            "Sector 62 Noida ke paas",  # location
            "Do log ghayal hain",  # details
        )
    )
    seq = _states(steps)
    # GREETING precedes INCIDENT_TYPE precedes LOCATION precedes DETAILS precedes ROUTE.
    order = [CallState.GREETING, CallState.INCIDENT_TYPE, CallState.LOCATION,
             CallState.DETAILS]
    last = -1
    for state in order:
        assert state in seq
        idx = seq.index(state)
        assert idx > last
        last = idx
    assert seq[-1] is CallState.ROUTE


def test_reasks_when_location_missing():
    # Incident is clear, but no location is ever given → machine clarifies once.
    steps = TriageStateMachine().drive(
        turns_of("Accident ho gaya khoon", "pata nahi kahan", "bas jaldi karo")
    )
    clarifies = [s for s in steps if s.clarify]
    assert clarifies, "expected at least one clarify/re-ask"
    assert any(s.ai_line == CLARIFY[s.state] for s in clarifies)


def test_clarify_capped(monkeypatch):
    # Never re-ask the same state more than MAX_CLARIFY times.
    steps = TriageStateMachine().drive(
        turns_of("hmm", "uhh", "pata nahi", "soch raha hoon")
    )
    by_state: dict = {}
    for s in steps:
        if s.clarify:
            by_state[s.state] = by_state.get(s.state, 0) + 1
    assert all(count <= MAX_CLARIFY for count in by_state.values())


def test_prompts_are_hindi_persona():
    assert "112" in prompt_for(CallState.GREETING)
    assert prompt_for(CallState.LOCATION)
    # Clarify variant differs from the primary.
    assert prompt_for(CallState.LOCATION, clarify=True) != prompt_for(CallState.LOCATION)
