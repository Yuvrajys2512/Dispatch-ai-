"""Pydantic domain model behaviour and validation."""

import uuid

import pytest
from pydantic import ValidationError

from app.domain.enums import CallState, Severity, Speaker
from app.domain.models import (
    CONFIDENCE_HANDOFF_THRESHOLD,
    Call,
    GeoPoint,
    IncidentCard,
)


def test_call_defaults():
    call = Call(phone="+91-98100-00000")
    assert isinstance(call.id, uuid.UUID)
    assert call.state is CallState.GREETING
    assert call.incident.incident_type.value == "UNKNOWN"
    assert call.transcript == []
    assert call.is_active
    assert call.route is None


def test_add_turn_assigns_monotonic_seq():
    call = Call(phone="+91-1")
    t0 = call.add_turn(Speaker.AI, "112 emergency")
    t1 = call.add_turn(Speaker.CALLER, "accident", confidence=0.9)
    assert (t0.seq, t1.seq) == (0, 1)
    assert call.transcript[-1].text == "accident"
    assert t1.confidence == 0.9


def test_incident_requires_handoff_on_high_severity():
    card = IncidentCard(severity=Severity.HIGH, confidence=0.99)
    assert card.requires_handoff


def test_incident_requires_handoff_on_low_confidence():
    card = IncidentCard(severity=Severity.LOW, confidence=CONFIDENCE_HANDOFF_THRESHOLD - 0.01)
    assert card.requires_handoff


def test_incident_no_handoff_when_confident_and_low_severity():
    card = IncidentCard(severity=Severity.MEDIUM, confidence=0.95)
    assert not card.requires_handoff


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        IncidentCard(confidence=1.5)
    with pytest.raises(ValidationError):
        IncidentCard(confidence=-0.1)


def test_geopoint_bounds():
    GeoPoint(lat=28.6, lng=77.4)
    with pytest.raises(ValidationError):
        GeoPoint(lat=200, lng=0)


def test_call_round_trips_through_json():
    call = Call(phone="+91-98100-00000")
    call.add_turn(Speaker.CALLER, "madad", confidence=0.8)
    call.incident.severity = Severity.CRITICAL
    raw = call.model_dump_json()
    restored = Call.model_validate_json(raw)
    assert restored.id == call.id
    assert restored.incident.severity is Severity.CRITICAL
    assert restored.transcript[0].text == "madad"
