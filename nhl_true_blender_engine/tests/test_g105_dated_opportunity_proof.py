"""G10.5 cannot defeat a same-lane recipient using unverified shot dates.

This guards against treating arbitrary historical count entries as distinct
actual NHL appearances while labeling the result tonight-specific.
"""
from nhl_true_blender_engine.engine import _same_lane_tonight_shot_opportunity
from nhl_true_blender_engine.tests.test_engine import skater


def _comparison():
    candidate = skater(85101, "slot", 18, 2)
    challenger = skater(85102, "slot", 6, 1)
    return candidate, challenger


def _run(candidate, challenger):
    return _same_lane_tonight_shot_opportunity(
        candidate, challenger,
        candidate["release"]["data"], challenger["release"]["data"],
        {"slot": {"shotsAgainst": 40, "goalsAgainst": 8}}, {"slot"},
    )


def test_dated_and_independently_observed_shot_pressure_can_be_compared():
    candidate, challenger = _comparison()
    proof = _run(candidate, challenger)
    assert proof is not None
    assert proof["result"] == "CANDIDATE"
    assert proof["bothHaveRecurringOwnShotPressure"] is True


def test_undated_shot_counts_cannot_defeat_a_teammate():
    candidate, challenger = _comparison()
    challenger["pressure"]["data"].pop("appearances")
    assert _run(candidate, challenger) is None


def test_duplicate_appearance_dates_are_not_two_actual_games():
    candidate, challenger = _comparison()
    challenger["pressure"]["data"]["appearances"][1]["date"] = "2026-11-01"
    assert _run(candidate, challenger) is None


def test_unmatched_shot_count_and_date_lists_cannot_set_recipient():
    candidate, challenger = _comparison()
    candidate["pressure"]["data"]["recentAppearanceShots"].append(3)
    assert _run(candidate, challenger) is None
