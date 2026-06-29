"""Triage keyword vocabulary — Hindi / Hinglish / English.

The severity classifier, junk scorer, and the hard safety override all share
this one vocabulary so they can never drift apart. Matching is intentionally
*lexical and deterministic* (no model in the loop): a real emergency must be
recognisable from words alone, because the mock LLM is too dumb to be trusted
with the severity decision and the real LLM (Phase 7) is too slow to be the only
guard. This is the "real classifier" the checklist asks for — it sits on top of
the LLM extraction, it does not depend on it.

Each tuple is a flat set of surface forms. Single tokens are matched on word
boundaries (so ``aag`` / "fire" does not fire inside ``bhaag`` / "run");
multi-word phrases are matched as substrings.
"""

from __future__ import annotations

import re

# --- CRITICAL: immediate threat to life (spec §4 🔴) ----------------------
# gun/knife, blood, breathing, unconscious, accident, fire, trapped, drowning,
# electrocution, gas/explosion, acid — plus Hindi/Hinglish forms.
CRITICAL: tuple[str, ...] = (
    "accident", "accidnt", "takkar", "takkar ho",
    "blood", "khoon", "khun", "bleeding", "lahu",
    "fire", "aag", "jal raha", "jal rahi", "blast", "dhamaka", "explosion",
    "gas leak", "gas lik",
    "unconscious", "behosh", "behoshi", "gir gaya", "gir gayi", "gir padi",
    "breathing", "saans nahi", "saans nai", "saans ruk", "dam ghut", "choking",
    "gun", "bandook", "pistol", "goli", "knife", "chaaku", "chaku", "churaa",
    "trapped", "phans gaya", "phas gaye", "dab gaya", "building collapse",
    "drowning", "doob raha", "doob gaya", "paani mein doob",
    "electrocution", "current laga", "bijli ka jhatka",
    "acid", "tezaab", "stab", "ghonp",
    "casualties", "many injured", "kai log ghayal", "do log ghayal",
    "not breathing", "saans nahi aa", "baby not breathing", "bachcha behosh",
)

# --- HIGH: serious but the immediate words above are absent (spec §4 🟠) ---
# assault/robbery in progress, medical (chest pain, seizure, fall, stroke),
# domestic violence.
HIGH: tuple[str, ...] = (
    "chest pain", "seene mein dard", "seene me dard", "seene mai dard",
    "heart attack", "dil ka daura",
    "seizure", "daura", "mirgi", "convuls", "jhatke aa rahe",
    "stroke", "paralysis", "lakwa", "mooh tedha",
    "robbery", "loot", "lut gaya", "luut", "daka",
    "assault", "maar raha", "maar rahe", "peet raha", "peet rahe", "hamla",
    "beating", "maara ja raha",
    "domestic violence", "ghar mein maar", "pati maar", "sasural maar",
    "fall", "gir kar chot", "chhat se gir", "height se gir",
    "fracture", "haddi tut", "haddi tuut",
    "allergic", "allergy reaction", "snake bite", "saap ne kaata", "saanp kaat",
    "kidnap", "uthwa liya", "utha liya", "agwa",
    "labour pain", "delivery", "bachcha hone", "prasav",
)

# --- THEFT / property (spec §4 🟡 MEDIUM): reported, not in progress -------
THEFT: tuple[str, ...] = (
    "chori", "theft", "stolen", "snatch", "snatching", "jhapatmaar",
    "phone chori", "purse chori", "chain snatch", "churaa liya", "chura liya",
    "burglary", "sendh", "ghar tuta", "saaman chori",
    "pickpocket", "jeb kati",
)

# --- DOMESTIC dispute (verbal) / nuisance (spec §4 🟡 MEDIUM) --------------
DOMESTIC_DISPUTE: tuple[str, ...] = (
    "jhagda", "jhagra", "ladai", "argument", "dispute", "bahas", "kahasuni",
    "verbal fight", "shor", "noise complaint", "noise", "hungama",
    "padosi jhagda", "neighbour dispute",
)

# --- PROPERTY damage (spec §4 🟡 MEDIUM) ----------------------------------
PROPERTY: tuple[str, ...] = (
    "property damage", "todfod", "gaadi tooti", "sheesha toot", "damage ho gaya",
    "fender bender", "minor accident", "halki tankar", "scratch",
)

# --- LOW: information requests / non-emergencies (spec §4 🟢) --------------
INFO_REQUEST: tuple[str, ...] = (
    "nearest hospital", "nearest station", "kaha hai", "kahan hai",
    "information chahiye", "jaankari", "puchna tha", "pata karna",
    "follow up", "follow-up", "complaint number", "shikayat number",
    "kab tak", "procedure", "how to", "kaise kare", "timing kya",
    "road closure", "rasta band",
)

# --- JUNK behavioural markers (spec §4 ⚪ + §Junk Detection) ---------------
LAUGHTER: tuple[str, ...] = (
    "haha", "hahaha", "hehe", "lol", "*laughing*", "*laugh*", "lmao",
    "hassi", "hass raha", "majak", "mazak", "mazaak",
)
TIMEPASS: tuple[str, ...] = (
    "timepass", "time pass", "tp", "bored", "bore ho", "just testing",
    "test kar raha", "fun", "masti", "khel raha",
)
WRONG_NUMBER: tuple[str, ...] = (
    "wrong number", "galat number", "galti se", "galti se lag",
    "sorry galti", "number galat",
)
LEWD: tuple[str, ...] = (
    "i love you", "i love u", "darling", "jaan", "sexy", "kiss",
    "shadi karogi", "girlfriend banogi", "boyfriend", "gandi baat",
)
# Crude abuse directed at the line — kept generic, transliterated.
ABUSE: tuple[str, ...] = (
    "abe", "saale", "chutiya", "bsdk", "madarchod", "behenchod", "gaali",
    "bakwas", "bakwaas",
)

# --- The HARD SAFETY OVERRIDE list (spec §Junk Detection, false-positive
# safeguard): "if a flagged-as-junk caller says any critical keyword
# (help, accident, blood, fire, bachao, madad), immediately reclassify and
# escalate." We carry the spec's six plus their obvious Indic variants and the
# unambiguous life-threat words. A bare cry for help ("bachao"/"madad"/"help")
# escalates to HIGH; a concrete life-threat word ("accident"/"blood"/"fire"/…)
# escalates to CRITICAL.
OVERRIDE_CRY: tuple[str, ...] = (
    "help", "help me", "madad", "madat", "bachao", "bachaao", "bacha lo",
    "save me", "please help", "koi help",
)
OVERRIDE_CRITICAL: tuple[str, ...] = (
    "accident", "blood", "khoon", "khun", "fire", "aag", "gun", "knife",
    "unconscious", "behosh", "saans nahi", "not breathing", "trapped",
    "phans gaya", "drowning", "doob raha", "stab", "acid", "tezaab",
)


def _matcher(terms: tuple[str, ...]) -> re.Pattern[str]:
    """Compile one regex that matches any term (word-bounded for single tokens,
    substring for phrases). Sorted longest-first so phrases win."""
    parts: list[str] = []
    for term in sorted(set(terms), key=len, reverse=True):
        esc = re.escape(term)
        if " " in term or "*" in term:
            parts.append(esc)
        else:
            parts.append(rf"\b{esc}\b")
    return re.compile("|".join(parts), re.IGNORECASE)


# Pre-compiled matchers (deterministic, built once).
CRITICAL_RE = _matcher(CRITICAL)
HIGH_RE = _matcher(HIGH)
THEFT_RE = _matcher(THEFT)
DOMESTIC_RE = _matcher(DOMESTIC_DISPUTE)
PROPERTY_RE = _matcher(PROPERTY)
INFO_RE = _matcher(INFO_REQUEST)
LAUGHTER_RE = _matcher(LAUGHTER)
TIMEPASS_RE = _matcher(TIMEPASS)
WRONG_NUMBER_RE = _matcher(WRONG_NUMBER)
LEWD_RE = _matcher(LEWD)
ABUSE_RE = _matcher(ABUSE)
OVERRIDE_CRY_RE = _matcher(OVERRIDE_CRY)
OVERRIDE_CRITICAL_RE = _matcher(OVERRIDE_CRITICAL)


def has(text: str, pattern: re.Pattern[str]) -> bool:
    return pattern.search(text) is not None
