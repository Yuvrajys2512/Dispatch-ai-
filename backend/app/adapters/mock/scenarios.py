"""Scripted call scenarios that drive the mock telephony/ASR and the Phase 3
triage corpus.

A :class:`Scenario` is a deterministic, replayable "call": a from-number, some
tags, an ordered list of caller utterances, optional caller reputation, and an
optional :class:`Expected` triage outcome. The mock telephony replays the turns
as synthetic audio; the mock ASR turns them back into partial→final transcript
chunks; the Phase 3 corpus test (``tests/agent/test_corpus.py``) runs each one
through the :class:`~app.agent.triage.TriageAgent` and asserts the outcome.

The first six scenarios are the original archetypes (and remain the demo default
via :data:`DEFAULT_SCENARIO_IDS`). Everything after them is the 50+-scenario
triage corpus the Phase 3 release gate runs against. The hard rule the corpus
enforces: **no genuine call is ever routed to JUNK** (zero false negatives),
including the adversarial "junk-that's-actually-real" cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScriptedTurn:
    """One caller utterance.

    ``confidence`` is the final ASR confidence the mock should report for this
    turn. ``silent`` models dead air after the greeting (a junk signal): the
    turn produces a brief, empty, low-confidence transcript.
    """

    text: str
    confidence: float = 0.9
    silent: bool = False


@dataclass(frozen=True)
class Expected:
    """The triage outcome a scenario should produce (asserted by the corpus).

    ``real_emergency`` marks a *genuine* call (anything that is not a prank /
    time-waster). The release gate asserts every ``real_emergency`` scenario is
    never severity JUNK and never routed to ``AUTO_RESOLVE``.
    """

    severity: str  # Severity value, e.g. "CRITICAL"
    route: str  # RouteTarget value, e.g. "OPERATOR_IMMEDIATE"
    handoff: bool
    real_emergency: bool


@dataclass(frozen=True)
class Scenario:
    id: str
    from_number: str
    tags: tuple[str, ...] = ()
    turns: tuple[ScriptedTurn, ...] = field(default_factory=tuple)
    expected: Expected | None = None
    # Caller reputation the junk scorer may weigh (Phase 6 sources this live).
    caller_calls_today: int = 0
    caller_blacklisted: bool = False
    caller_flagged_prank: bool = False


# Convenience aliases for terse expectations below.
_CRIT = "CRITICAL"
_HIGH = "HIGH"
_MED = "MEDIUM"
_LOW = "LOW"
_JUNK = "JUNK"
_IMMED = "OPERATOR_IMMEDIATE"
_QUEUE = "OPERATOR_QUEUE"
_AI = "AI_RESOLVE"
_AUTO = "AUTO_RESOLVE"


def _t(text: str, conf: float = 0.9, silent: bool = False) -> ScriptedTurn:
    return ScriptedTurn(text, conf, silent)


# --- Starter archetypes (also the demo default) ---------------------------

ACCIDENT = Scenario(
    id="accident_injuries",
    from_number="+91-98100-00001",
    tags=("accident", "critical", "injuries"),
    turns=(
        _t("Accident ho gaya, do log ghayal hain, khoon nikal raha hai!", 0.91),
        _t("NH-24 par, Ghaziabad toll plaza ke paas.", 0.88),
        _t("Haan ambulance bhej do jaldi!", 0.9),
    ),
    expected=Expected(_CRIT, _IMMED, True, True),
)

THEFT = Scenario(
    id="theft_reported",
    from_number="+91-70000-00002",
    tags=("theft", "medium"),
    turns=(
        _t("Mera phone chori ho gaya abhi thodi der pehle.", 0.88),
        _t("Sector 62, Noida, metro station ke paas.", 0.86),
    ),
    expected=Expected(_MED, _QUEUE, False, True),
)

CHEST_PAIN = Scenario(
    id="medical_chest_pain",
    from_number="+91-99999-00003",
    tags=("medical", "critical"),
    turns=(
        _t("Mere papa ko seene mein bahut dard ho raha hai, saans nahi aa rahi.", 0.84),
        _t("Ghar par hain, Lajpat Nagar.", 0.87),
    ),
    expected=Expected(_CRIT, _IMMED, True, True),
)

PRANK_LAUGHTER = Scenario(
    id="prank_laughter",
    from_number="+91-63000-00004",
    tags=("junk", "prank"),
    turns=(
        _t("hahaha hello hello *laughing*", 0.55),
        _t("arre kuch nahi timepass", 0.5),
    ),
    expected=Expected(_JUNK, _AUTO, False, False),
)

SILENT = Scenario(
    id="silent_accidental",
    from_number="+91-63000-00005",
    tags=("junk", "silent"),
    turns=(_t("", 0.2, silent=True),),
    expected=Expected(_JUNK, _AUTO, False, False),
)

BROKEN_HINDI = Scenario(
    id="broken_hindi_english",
    from_number="+91-80000-00006",
    tags=("accident", "code-switch", "adversarial"),
    turns=(
        _t("Sir wo... accident... my brother bahut hurt hai please help", 0.7),
        _t("near the... uh... DLF mall Gurgaon", 0.68),
    ),
    expected=Expected(_CRIT, _IMMED, True, True),
)

_ARCHETYPES = (ACCIDENT, THEFT, CHEST_PAIN, PRANK_LAUGHTER, SILENT, BROKEN_HINDI)


# --- CRITICAL: immediate threat to life -----------------------------------

_CRITICAL_SET = (
    Scenario(
        id="building_fire",
        from_number="+91-98100-10001",
        tags=("fire", "critical"),
        turns=(
            _t("Building mein aag lag gayi hai, dhuaan bhar gaya, log phans gaye!", 0.9),
            _t("Karol Bagh, paanchvi manzil par.", 0.88),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="gun_threat",
        from_number="+91-98100-10002",
        tags=("weapon", "critical"),
        turns=(
            _t("Ek aadmi bandook le kar khada hai, goli chala raha hai!", 0.88),
            _t("Connaught Place, block A ke paas.", 0.86),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="knife_attack",
        from_number="+91-98100-10003",
        tags=("weapon", "critical"),
        turns=(
            _t("Kisi ne chaaku se vaar kiya, bahut khoon beh raha hai!", 0.86),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="child_drowning",
        from_number="+91-98100-10004",
        tags=("medical", "critical", "child"),
        turns=(
            _t("Mera bachcha paani mein doob raha hai, bachao!", 0.8),
            _t("Yamuna ghaat, ITO ke paas.", 0.82),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="electrocution",
        from_number="+91-98100-10005",
        tags=("medical", "critical"),
        turns=(
            _t("Mere bhai ko current laga, behosh ho gaya hai!", 0.85),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="gas_explosion",
        from_number="+91-98100-10006",
        tags=("fire", "critical"),
        turns=(
            _t("Gas leak ho gayi thi, dhamaka ho gaya, do log ghayal hain.", 0.84),
            _t("Rohini sector 7.", 0.86),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="building_collapse",
        from_number="+91-98100-10007",
        tags=("critical", "rescue"),
        turns=(
            _t("Building gir gayi, kai log malbe mein dab gaye hain!", 0.83),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="heavy_bleeding",
        from_number="+91-98100-10008",
        tags=("medical", "critical"),
        turns=(
            _t("Bahut khoon nikal raha hai, ruk nahi raha, woh behosh ho rahe hain.", 0.82),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="acid_attack",
        from_number="+91-98100-10009",
        tags=("assault", "critical"),
        turns=(
            _t("Kisi ne ek ladki par tezaab phenk diya, woh cheekh rahi hai!", 0.8),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="baby_not_breathing",
        from_number="+91-98100-10010",
        tags=("medical", "critical", "child"),
        turns=(
            _t("Mera navjaat bachcha saans nahi le raha, behosh hai!", 0.78),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="highway_pileup",
        from_number="+91-98100-10011",
        tags=("accident", "critical"),
        turns=(
            _t("Highway par badi takkar ho gayi, kai gaadiyan, log ghayal hain.", 0.85),
            _t("Yamuna Expressway, Mathura ke paas.", 0.84),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="snake_bite_collapse",
        from_number="+91-98100-10012",
        tags=("medical", "critical"),
        turns=(
            _t("Saanp ne kaata, ab behosh ho gaye hain aur saans nahi aa rahi.", 0.8),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="kidnap_child",
        from_number="+91-98100-10013",
        tags=("assault", "critical", "child"),
        turns=(
            _t("Koi mere bachche ka agwa kar raha hai, bachao!", 0.83),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="fever_convulsion_child",
        from_number="+91-98100-10014",
        tags=("medical", "critical", "child"),
        turns=(
            _t("Bachche ko tez bukhar hai aur jhatke aa rahe hain!", 0.8),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
)


# --- HIGH: serious, priority handoff --------------------------------------

_HIGH_SET = (
    Scenario(
        id="chest_pain_only",
        from_number="+91-98100-20001",
        tags=("medical", "high"),
        turns=(
            _t("Papa ke seene mein dard ho raha hai, bahut takleef hai.", 0.88),
            _t("Ghar par hain, Pitampura.", 0.87),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="seizure",
        from_number="+91-98100-20002",
        tags=("medical", "high"),
        turns=(
            _t("Bhai ko daura pad raha hai, mirgi ke jhatke aa rahe.", 0.86),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="stroke",
        from_number="+91-98100-20003",
        tags=("medical", "high"),
        turns=(
            _t("Mummy ka mooh tedha ho gaya, lagta hai lakwa laga hai.", 0.85),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="robbery_in_progress",
        from_number="+91-98100-20004",
        tags=("crime", "high"),
        turns=(
            _t("Abhi do aadmi dukaan loot rahe hain, jaldi karo!", 0.86),
            _t("Sadar Bazaar, main road.", 0.85),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="assault_ongoing",
        from_number="+91-98100-20005",
        tags=("assault", "high"),
        turns=(
            _t("Kuch log mujhe maar rahe hain, hamla kar diya.", 0.84),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="domestic_violence",
        from_number="+91-98100-20006",
        tags=("domestic", "high"),
        turns=(
            _t("Mera pati mujhe maar raha hai, bachao please.", 0.8),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="fall_from_height",
        from_number="+91-98100-20007",
        tags=("medical", "high"),
        turns=(
            _t("Chhat se gir kar bhai ko chot lagi, haddi tut gayi.", 0.85),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="severe_allergy",
        from_number="+91-98100-20008",
        tags=("medical", "high"),
        turns=(
            _t("Bhai ko allergic reaction ho gaya, soojan aa rahi hai.", 0.82),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="kidnap_attempt_adult",
        from_number="+91-98100-20009",
        tags=("crime", "high"),
        turns=(
            _t("Koi aadmi meri behen ka agwa karne ki koshish kar raha hai.", 0.83),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="labour_emergency",
        from_number="+91-98100-20010",
        tags=("medical", "high"),
        turns=(
            _t("Meri patni ko prasav ki peeda ho rahi hai, delivery abhi hone wali hai.", 0.85),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
)


# --- MEDIUM: genuine, queued ----------------------------------------------

_MEDIUM_SET = (
    Scenario(
        id="phone_snatched_past",
        from_number="+91-98100-30001",
        tags=("theft", "medium"),
        turns=(
            _t("Thodi der pehle mera phone snatch ho gaya tha.", 0.88),
            _t("Lajpat Nagar market ke paas.", 0.87),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="burglary_discovered",
        from_number="+91-98100-30002",
        tags=("theft", "medium"),
        turns=(
            _t("Ghar aaye to dekha sendh lagi hui hai, saaman chori ho gaya.", 0.87),
            _t("Mayur Vihar phase 1.", 0.86),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="chain_snatching_past",
        from_number="+91-98100-30003",
        tags=("theft", "medium"),
        turns=(
            _t("Subah meri chain snatch kar li thi kisi ne bike par.", 0.86),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="pickpocket_bus",
        from_number="+91-98100-30004",
        tags=("theft", "medium"),
        turns=(
            _t("Bus mein meri jeb kati, paisa chori ho gaya.", 0.86),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="noise_complaint",
        from_number="+91-98100-30005",
        tags=("nuisance", "medium"),
        turns=(
            _t("Padosi raat bhar bahut shor aur hungama kar rahe hain.", 0.9),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="property_damage",
        from_number="+91-98100-30006",
        tags=("property", "medium"),
        turns=(
            _t("Kisi ne meri gaadi ka sheesha tod diya aur todfod ki.", 0.88),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="verbal_dispute",
        from_number="+91-98100-30007",
        tags=("dispute", "medium"),
        turns=(
            _t("Padosi se zameen ko lekar jhagda aur bahas ho rahi hai.", 0.87),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
    Scenario(
        id="minor_fender_bender",
        from_number="+91-98100-30008",
        tags=("property", "medium"),
        turns=(
            _t("Halki tankar ho gayi, koi ghayal nahi, bas gaadi ka damage hua.", 0.88),
        ),
        expected=Expected(_MED, _QUEUE, False, True),
    ),
)


# --- LOW: non-emergency, AI may resolve -----------------------------------

_LOW_SET = (
    Scenario(
        id="info_nearest_hospital",
        from_number="+91-98100-40001",
        tags=("info", "low"),
        turns=(
            _t("Sabse paas hospital kahan hai, jaankari chahiye thi.", 0.92),
        ),
        expected=Expected(_LOW, _AI, False, True),
    ),
    Scenario(
        id="complaint_followup",
        from_number="+91-98100-40002",
        tags=("info", "low"),
        turns=(
            _t("Meri purani shikayat number ka follow up karna tha.", 0.9),
        ),
        expected=Expected(_LOW, _AI, False, True),
    ),
    Scenario(
        id="procedure_query",
        from_number="+91-98100-40003",
        tags=("info", "low"),
        turns=(
            _t("112 par complaint kaise darj kare, procedure kya hai?", 0.91),
        ),
        expected=Expected(_LOW, _AI, False, True),
    ),
    Scenario(
        id="road_closure_info",
        from_number="+91-98100-40004",
        tags=("info", "low"),
        turns=(
            _t("Kya aaj NH-9 ka rasta band hai, jaankari chahiye.", 0.9),
        ),
        expected=Expected(_LOW, _AI, False, True),
    ),
)


# --- JUNK: pranks / time-wasters ------------------------------------------

_JUNK_SET = (
    Scenario(
        id="kids_playing",
        from_number="+91-63000-50001",
        tags=("junk", "prank"),
        turns=(
            _t("hahaha mummy dekho phone *laughing* hehe", 0.5),
        ),
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="wrong_number",
        from_number="+91-63000-50002",
        tags=("junk", "wrong-number"),
        turns=(
            _t("Oh sorry galat number lag gaya, galti se.", 0.85),
        ),
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="lewd_call",
        from_number="+91-63000-50003",
        tags=("junk", "lewd"),
        turns=(
            _t("i love you madam aapki aawaz sexy hai darling", 0.8),
        ),
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="abusive_call",
        from_number="+91-63000-50004",
        tags=("junk", "abuse"),
        turns=(
            _t("abe saale bakwas band kar, gaali dunga", 0.8),
        ),
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="party_noise",
        from_number="+91-63000-50005",
        tags=("junk", "prank"),
        turns=(
            _t("hahaha music loud hai *laughing* party chal rahi hai", 0.5),
        ),
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="repeat_prank_caller",
        from_number="+91-63000-50006",
        tags=("junk", "repeat"),
        turns=(
            _t("haha hello kaun hai timepass kar raha hoon", 0.6),
        ),
        caller_calls_today=5,
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="blacklisted_caller",
        from_number="+91-63000-50007",
        tags=("junk", "blacklist"),
        turns=(
            _t("kuch nahi bas aise hi call kiya tha", 0.7),
        ),
        caller_blacklisted=True,
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
    Scenario(
        id="just_testing",
        from_number="+91-63000-50008",
        tags=("junk", "borderline"),
        turns=(
            _t("bas test kar raha tha 112 kaam karta hai kya", 0.8),
        ),
        # Borderline junk → not confident enough to auto-resolve → human checks.
        expected=Expected(_JUNK, _IMMED, True, False),
    ),
    Scenario(
        id="pocketdial_accidental_sos",
        from_number="+91-63000-50009",
        tags=("junk", "accidental-sos"),
        turns=(
            _t("", 0.2, silent=True),
            _t("khhh", 0.3),
        ),
        # Accidental SOS button: dead air + a stray noise → auto-resolved.
        expected=Expected(_JUNK, _AUTO, False, False),
    ),
)


# --- ADVERSARIAL: junk-looking but REAL (must never be JUNK) ---------------

_ADVERSARIAL_SET = (
    Scenario(
        id="crying_child_real",
        from_number="+91-90000-60001",
        tags=("medical", "critical", "adversarial"),
        turns=(
            _t("*crying* mummy gir gayi ... khoon nikal raha hai bachao", 0.5),
        ),
        caller_flagged_prank=True,
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="nervous_laugh_bachao",
        from_number="+91-90000-60002",
        tags=("adversarial", "override"),
        turns=(
            _t("hahaha ... bachao bachao koi hai please", 0.5),
        ),
        caller_flagged_prank=True,
        # No concrete incident word — only a cry masked by laughter. The
        # critical-keyword override is what saves this call.
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="broken_english_fire",
        from_number="+91-90000-60003",
        tags=("fire", "critical", "adversarial"),
        turns=(
            _t("help help ... fire fire building burning please", 0.55),
        ),
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="repeat_caller_real_accident",
        from_number="+91-90000-60004",
        tags=("accident", "critical", "adversarial"),
        turns=(
            _t("accident ho gaya bachao, do log ghayal hain", 0.7),
        ),
        caller_calls_today=4,
        caller_flagged_prank=True,
        expected=Expected(_CRIT, _IMMED, True, True),
    ),
    Scenario(
        id="slurred_chest_pain",
        from_number="+91-90000-60005",
        tags=("medical", "high", "adversarial"),
        turns=(
            _t("seene me dard ho raha hai ... saans bhaari hai", 0.6),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="whisper_domestic",
        from_number="+91-90000-60006",
        tags=("domestic", "high", "adversarial"),
        turns=(
            _t("chupke se bol rahi hoon ... pati maar raha hai bachao", 0.55),
        ),
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
    Scenario(
        id="silent_then_faint_cry",
        from_number="+91-90000-60007",
        tags=("adversarial", "override"),
        turns=(
            _t("", 0.2, silent=True),
            _t("koi ... help karo bachao", 0.5),
        ),
        # Looks like a silent/junk call, then a faint cry — must escalate.
        expected=Expected(_HIGH, _IMMED, True, True),
    ),
)


_ALL: tuple[Scenario, ...] = (
    *_ARCHETYPES,
    *_CRITICAL_SET,
    *_HIGH_SET,
    *_MEDIUM_SET,
    *_LOW_SET,
    *_JUNK_SET,
    *_ADVERSARIAL_SET,
)

SCENARIOS: dict[str, Scenario] = {s.id: s for s in _ALL}

# The original six archetypes remain the telephony/demo default so existing
# adapter behaviour is unchanged.
DEFAULT_SCENARIO_IDS: tuple[str, ...] = tuple(s.id for s in _ARCHETYPES)

# The full Phase 3 triage corpus (every scenario carries an Expected outcome).
TRIAGE_CORPUS: tuple[Scenario, ...] = tuple(s for s in _ALL if s.expected is not None)


def get_scenario(scenario_id: str) -> Scenario:
    return SCENARIOS[scenario_id]
