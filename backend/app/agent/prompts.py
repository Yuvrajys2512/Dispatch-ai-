"""Per-state prompt templates — calm, authoritative Hindi/Hinglish persona.

The agent speaks like a trained 112 call-taker: short sentences, reassuring,
always moving the caller toward the next piece of information triage needs. Each
:class:`~app.domain.enums.CallState` has a primary prompt and a *clarify* (re-ask)
variant for when the previous answer didn't land. Templates are plain strings so
they stay testable and the real TTS (Phase 7) can speak them unchanged.
"""

from __future__ import annotations

from app.domain.enums import CallState

# Primary prompt spoken when the agent first enters a state.
PROMPTS: dict[CallState, str] = {
    CallState.GREETING: "112 emergency. Main aapki kya madad kar sakta hoon? Kya hua hai?",
    CallState.INCIDENT_TYPE: "Aap shaant rahiye. Mujhe bataaiye, kya hua hai — accident, "
    "aag, chori, ya koi medical emergency?",
    CallState.LOCATION: "Aap abhi kahaan par hain? Koi paas ka landmark ya address bataaiye.",
    CallState.DETAILS: "Theek hai. Kitne log involved hain, aur kya koi ghayal hai? "
    "Kya ambulance ya police chahiye?",
    CallState.SEVERITY_SCORE: "Samajh gaya. Main aapki call ko priority de raha hoon.",
    CallState.ROUTE: "Madad bhej di gayi hai. Aap line par baney rahiye, ghabraaiye mat.",
}

# Spoken when the agent has to re-ask because the answer was missing/unclear.
CLARIFY: dict[CallState, str] = {
    CallState.INCIDENT_TYPE: "Maaf kijiye, main theek se sun nahi paaya. Dheere se "
    "bataaiye — kya emergency hai?",
    CallState.LOCATION: "Mujhe aapki location chahiye taaki madad bhej sakoon. "
    "Aas-paas kya dikh raha hai?",
    CallState.DETAILS: "Ek baar aur — kitne log hain aur kya chot lagi hai?",
}

# What the agent says the moment it hands a live call to a human operator.
HANDOFF_LINE = (
    "Main aapko abhi ek senior officer se jod raha hoon. Aap line par baney rahiye."
)


def prompt_for(state: CallState, *, clarify: bool = False) -> str:
    """Return the line to speak for ``state`` (the clarify variant if re-asking)."""
    if clarify and state in CLARIFY:
        return CLARIFY[state]
    return PROMPTS.get(state, PROMPTS[CallState.GREETING])
