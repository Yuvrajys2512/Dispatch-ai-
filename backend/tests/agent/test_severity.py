"""Severity classifier — the spec §4 urgency ladder, from signals alone."""

from app.agent.severity import classify_severity
from app.domain.enums import IncidentType, Severity
from tests.agent.helpers import signals_for


def _sev(*texts: str) -> Severity:
    return classify_severity(signals_for(*texts)).severity


def test_critical_life_threat_keywords():
    assert _sev("Accident ho gaya, khoon nikal raha hai") is Severity.CRITICAL
    assert _sev("Building mein aag lagi hai") is Severity.CRITICAL
    assert _sev("Ek aadmi bandook se goli chala raha hai") is Severity.CRITICAL
    assert _sev("Bachcha paani mein doob raha hai") is Severity.CRITICAL
    assert _sev("Saans nahi aa rahi, behosh ho gaye") is Severity.CRITICAL


def test_high_serious_but_not_immediate():
    assert _sev("Papa ke seene mein dard ho raha hai") is Severity.HIGH
    assert _sev("Bhai ko daura pad raha hai") is Severity.HIGH
    assert _sev("Do aadmi dukaan loot rahe hain") is Severity.HIGH
    assert _sev("Pati mujhe maar raha hai") is Severity.HIGH


def test_medium_theft_property_dispute():
    assert _sev("Mera phone chori ho gaya") is Severity.MEDIUM
    assert _sev("Padosi se jhagda ho raha hai") is Severity.MEDIUM
    assert _sev("Gaadi ka sheesha tod diya todfod ki") is Severity.MEDIUM


def test_low_information_request():
    assert _sev("Sabse paas hospital kahan hai jaankari chahiye") is Severity.LOW


def test_unclassified_spoken_defaults_medium_never_junk():
    # A spoken call we can't classify is conservatively MEDIUM — never JUNK.
    # (Junk is decided separately, by the junk scorer.)
    v = _sev("kuch ajeeb sa ho raha hai samajh nahi aa raha")
    assert v is Severity.MEDIUM


def test_multiple_casualties_force_critical():
    assert _sev("Kai log ghayal hain yahan") is Severity.CRITICAL


def test_child_distress_escalates_high_to_critical():
    v = classify_severity(signals_for("Bachche ko daura pad raha hai jhatke aa rahe"))
    assert v.severity is Severity.CRITICAL


def test_incident_type_and_service_needs():
    v = classify_severity(signals_for("Accident ho gaya do log ghayal, ambulance chahiye"))
    assert v.incident_type is IncidentType.ACCIDENT
    assert v.needs_ambulance is True
    assert v.needs_police is True

    fire = classify_severity(signals_for("Ghar mein aag lag gayi"))
    assert fire.incident_type is IncidentType.FIRE
    assert fire.needs_fire is True


def test_reasons_are_populated():
    assert classify_severity(signals_for("Accident khoon")).reasons
