"""Non-Core G0 uncertainty remains visible but does not erase a verified Core.

This partitions error reporting only; it never modifies any original G0-G18
gate, player disposition, starter status, or Core selection.
"""
from nhl_true_blender_engine.engine import partition_nonselected_g0_diagnostics


def test_consensus_multiple_goalies_in_other_game_is_not_core_fatal():
    ambiguous = ("5003 G0 source consensus exists but multiple potential "
                 "opposing goalies remain; cannot bind unique scorer-to-goalie route")
    remaining, notes = partition_nonselected_g0_diagnostics(
        [ambiguous], {"5001", "5002", "5004"})
    assert remaining == []
    assert notes == [ambiguous]


def test_selected_game_consensus_ambiguity_is_still_fatal():
    ambiguous = ("5001 G0 source consensus exists but multiple potential "
                 "opposing goalies remain; cannot bind unique scorer-to-goalie route")
    remaining, notes = partition_nonselected_g0_diagnostics(
        [ambiguous], {"5001", "5002", "5004"})
    assert remaining == [ambiguous]
    assert notes == []


def test_non_g0_errors_and_pre_core_review_stay_fatal():
    messages = [
        "5003 PRE_CORE_REVIEW: two same-game recipients remain",
        "5003 G17 an unresolved contradiction",
        "G16 finalist competition unresolved",
        {"reason": "source feed unavailable"},
    ]
    remaining, notes = partition_nonselected_g0_diagnostics(
        messages, {"5001", "5002", "5004"})
    assert remaining == messages
    assert notes == []


def test_other_unresolved_g0_issues_still_reported_by_game():
    other = "5003 G0 both attack directions REQUIRE independent goalie profiles; one-sided source presence is NOT a selection rule"
    remaining, notes = partition_nonselected_g0_diagnostics(
        [other], {"5001", "5002", "5004"})
    assert remaining == []
    assert notes == [other]
