"""Domain enum behaviour — especially the severity ordering the safety rule needs."""

from app.domain.enums import CallState, Severity


def test_severity_ordering_is_urgency_based():
    assert Severity.CRITICAL > Severity.HIGH
    assert Severity.HIGH > Severity.MEDIUM
    assert Severity.MEDIUM > Severity.LOW
    assert Severity.LOW > Severity.JUNK


def test_severity_ge_threshold_for_handoff():
    # The spec's "severity >= HIGH => handoff" must hold for CRITICAL and HIGH only.
    assert Severity.CRITICAL >= Severity.HIGH
    assert Severity.HIGH >= Severity.HIGH
    assert not (Severity.MEDIUM >= Severity.HIGH)
    assert not (Severity.JUNK >= Severity.HIGH)


def test_severity_rank_values():
    assert Severity.CRITICAL.rank == 4
    assert Severity.JUNK.rank == 0


def test_call_state_terminal_flags():
    assert CallState.ROUTED.is_terminal
    assert CallState.HANDED_OVER.is_terminal
    assert CallState.RESOLVED.is_terminal
    assert CallState.ABANDONED.is_terminal
    assert not CallState.GREETING.is_terminal
    assert not CallState.LOCATION.is_terminal


def test_enums_serialize_to_their_string_value():
    assert Severity.CRITICAL.value == "CRITICAL"
    assert str(Severity.CRITICAL.value) == "CRITICAL"
