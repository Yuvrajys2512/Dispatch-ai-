"""Conversation agent — the brain (Phase 3).

Turns a conversation into a correct, safe IncidentCard + severity + route,
independent of telephony/audio. The safety rules (severity ≥ HIGH or
confidence < 0.80 ⇒ handoff; critical-keyword override) are enforced here and
gated by ``tests/agent/test_safety.py``.
"""

from app.agent.junk import JunkAssessment, score_junk
from app.agent.safety import (
    compute_confidence,
    critical_keyword_override,
    decide_route,
    requires_handoff,
)
from app.agent.severity import SeverityVerdict, classify_severity
from app.agent.signals import (
    CallerContext,
    CallerTurn,
    ConversationSignals,
    build_signals,
)
from app.agent.state_machine import DialogueStep, TriageStateMachine
from app.agent.triage import TriageAgent, TriageOutcome

__all__ = [
    "CallerContext",
    "CallerTurn",
    "ConversationSignals",
    "DialogueStep",
    "JunkAssessment",
    "SeverityVerdict",
    "TriageAgent",
    "TriageOutcome",
    "TriageStateMachine",
    "build_signals",
    "classify_severity",
    "compute_confidence",
    "critical_keyword_override",
    "decide_route",
    "requires_handoff",
    "score_junk",
]
