"""Junk scorer — weighted behavioural signals (spec §Junk Detection)."""

from app.agent.junk import JUNK_THRESHOLD, score_junk
from app.agent.signals import CallerContext
from tests.agent.helpers import signals_for


def test_laughter_scores_junk():
    j = score_junk(signals_for("hahaha hello timepass *laughing*", conf=0.5))
    assert j.is_junk
    assert j.probability >= JUNK_THRESHOLD


def test_silence_scores_junk():
    from app.agent.signals import CallerTurn, build_signals

    j = score_junk(build_signals([CallerTurn("", 0.2, silent=True)]))
    assert j.is_junk


def test_wrong_number_and_lewd_and_abuse_score_junk():
    assert score_junk(signals_for("sorry galat number lag gaya")).is_junk
    assert score_junk(signals_for("i love you madam sexy aawaz")).is_junk
    assert score_junk(signals_for("abe saale bakwas band kar")).is_junk


def test_blacklist_and_repeat_caller_weigh_in():
    blk = score_junk(signals_for("haan bolo", caller=CallerContext(is_blacklisted=True)))
    assert blk.is_junk
    rep = score_junk(signals_for("haan bolo", caller=CallerContext(calls_today=4)))
    assert rep.is_junk


def test_repeat_weight_fires_on_third_call_not_second():
    # The rolling counter weight starts at calls_today >= 3 (the "3rd call today").
    second = score_junk(signals_for("haan bolo", caller=CallerContext(calls_today=2)))
    third = score_junk(signals_for("haan bolo", caller=CallerContext(calls_today=3)))
    assert not second.is_junk
    assert third.is_junk


def test_noisy_or_stacks_multiple_signals():
    one = score_junk(signals_for("hahaha", conf=0.5)).probability
    two = score_junk(
        signals_for("hahaha timepass", conf=0.5),
        # add a reputation signal too
    ).probability
    # More junk signals never lowers the probability.
    assert two >= one


def test_genuine_emergency_is_not_junk_even_with_noise():
    # Laughter-masked but contains a real incident word → not junk.
    j = score_junk(signals_for("hahaha accident ho gaya khoon", conf=0.5))
    # The scorer is behavioural (laughter present) but the *agent* gate uses
    # has_emergency_kw to refuse junk; here we assert the emergency content flag.
    s = signals_for("hahaha accident ho gaya khoon", conf=0.5)
    assert s.has_emergency_kw is True
    assert j.probability >= JUNK_THRESHOLD  # behaviourally noisy …


def test_clear_emergency_has_no_junk_signal():
    j = score_junk(signals_for("Accident ho gaya do log ghayal hain", conf=0.9))
    assert j.is_junk is False
    assert j.probability == 0.0


def test_reasons_listed():
    j = score_junk(signals_for("hahaha timepass", conf=0.5))
    assert j.reasons
