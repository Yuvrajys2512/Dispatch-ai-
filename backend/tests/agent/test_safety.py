"""SAFETY — the hard, non-negotiable rules. This file must pass 100%.

It encodes spec §4's "CRITICAL SAFETY RULE" and §Junk's false-positive
safeguard as executable invariants:

  1. severity ≥ HIGH        ⇒ instant handoff
  2. confidence < 0.80      ⇒ instant handoff
  3. critical keyword in a junk-looking call ⇒ reclassify & escalate

A regression here is a build-blocker (release gate: zero false negatives,
safety-rule integrity).
"""

import pytest

from app.agent.junk import score_junk
from app.agent.safety import (
    compute_confidence,
    critical_keyword_override,
    decide_route,
    requires_handoff,
)
from app.domain.enums import RouteTarget, Severity
from app.domain.models import CONFIDENCE_HANDOFF_THRESHOLD, IncidentCard
from tests.agent.helpers import signals_for

# --- Rule 3: critical-keyword override (junk → escalate) ------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("hahaha accident ho gaya", Severity.CRITICAL),
        ("timepass khoon nikal raha hai", Severity.CRITICAL),
        ("*laughing* aag lag gayi", Severity.CRITICAL),
        ("bachao bachao koi hai", Severity.HIGH),
        ("please madad karo", Severity.HIGH),
        ("help help", Severity.HIGH),
    ],
)
def test_override_escalates_junk_with_critical_keyword(text, expected):
    # Even if everything upstream concluded JUNK, the override re-escalates.
    out = critical_keyword_override(Severity.JUNK, signals_for(text, conf=0.4))
    assert out is expected


def test_override_never_lowers_severity():
    # An already-critical call is never demoted by the override.
    sig = signals_for("Accident ho gaya khoon", conf=0.9)
    assert critical_keyword_override(Severity.CRITICAL, sig) is Severity.CRITICAL


def test_override_noop_without_keyword():
    sig = signals_for("kuch samajh nahi aa raha", conf=0.5)
    assert critical_keyword_override(Severity.JUNK, sig) is Severity.JUNK
    assert critical_keyword_override(Severity.LOW, sig) is Severity.LOW


# --- Rule 1 & 2: handoff predicate ----------------------------------------


def test_high_or_above_always_hands_off():
    for sev in (Severity.HIGH, Severity.CRITICAL):
        assert requires_handoff(sev, confidence=0.99) is True


def test_low_confidence_always_hands_off():
    below = CONFIDENCE_HANDOFF_THRESHOLD - 0.01
    for sev in (Severity.MEDIUM, Severity.LOW, Severity.JUNK):
        assert requires_handoff(sev, confidence=below) is True


def test_confident_non_emergency_does_not_hand_off():
    assert requires_handoff(Severity.MEDIUM, confidence=0.95) is False
    assert requires_handoff(Severity.LOW, confidence=0.95) is False
    assert requires_handoff(Severity.JUNK, confidence=0.95) is False


def test_threshold_is_exclusive_lower_bound():
    # Exactly 0.80 is acceptable (rule is "< 0.80").
    assert requires_handoff(Severity.MEDIUM, CONFIDENCE_HANDOFF_THRESHOLD) is False
    assert requires_handoff(Severity.MEDIUM, CONFIDENCE_HANDOFF_THRESHOLD - 1e-9) is True


def test_predicate_matches_incident_card_property():
    # The safety predicate and the domain helper must never diverge.
    for sev in Severity:
        for conf in (0.0, 0.5, 0.79, 0.8, 0.95, 1.0):
            card = IncidentCard(severity=sev, confidence=conf)
            assert requires_handoff(sev, conf) == card.requires_handoff


# --- Routing enforces the floors ------------------------------------------


def test_route_high_severity_is_immediate():
    card = IncidentCard(severity=Severity.CRITICAL, confidence=0.99)
    assert decide_route(card).target is RouteTarget.OPERATOR_IMMEDIATE


def test_route_low_confidence_is_immediate_even_if_medium():
    card = IncidentCard(severity=Severity.MEDIUM, confidence=0.5)
    r = decide_route(card)
    assert r.target is RouteTarget.OPERATOR_IMMEDIATE
    assert r.handoff is True


def test_route_confident_junk_auto_resolves():
    card = IncidentCard(severity=Severity.JUNK, confidence=0.95)
    assert decide_route(card).target is RouteTarget.AUTO_RESOLVE


def test_route_unsure_junk_is_handed_off_not_dropped():
    # A junk guess we're not confident about must reach a human, never AUTO.
    card = IncidentCard(severity=Severity.JUNK, confidence=0.6)
    assert decide_route(card).target is RouteTarget.OPERATOR_IMMEDIATE


def test_route_confident_medium_queues_and_low_ai_resolves():
    assert decide_route(
        IncidentCard(severity=Severity.MEDIUM, confidence=0.9)
    ).target is RouteTarget.OPERATOR_QUEUE
    assert decide_route(
        IncidentCard(severity=Severity.LOW, confidence=0.9)
    ).target is RouteTarget.AI_RESOLVE


# --- Confidence semantics --------------------------------------------------


def test_junk_confidence_tracks_junk_probability():
    sig = signals_for("hahaha timepass *laughing*", conf=0.5)
    junk = score_junk(sig)
    assert compute_confidence(sig, Severity.JUNK, junk) == round(
        min(junk.probability, 0.99), 2
    )


def test_unclear_speech_lowers_confidence():
    clear = signals_for("Papa ke seene mein dard ho raha hai", conf=0.9)
    broken = signals_for("seene mein dard ... uh saans", conf=0.6)
    junk = score_junk(clear)
    assert compute_confidence(broken, Severity.HIGH, score_junk(broken)) < (
        compute_confidence(clear, Severity.HIGH, junk)
    )


def test_no_real_emergency_can_be_auto_resolved_invariant():
    # Construct the worst case: an emergency the AI is *certain* about. It still
    # must hand off (severity floor), never AUTO_RESOLVE.
    for sev in (Severity.CRITICAL, Severity.HIGH):
        card = IncidentCard(severity=sev, confidence=1.0)
        assert decide_route(card).target is not RouteTarget.AUTO_RESOLVE
        assert card.requires_handoff is True
