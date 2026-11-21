"""Regression: unknown NHL rink coordinates are uncertainty, never zero shots.

These tests use synthetic official-shaped dated PBP/boxscore receipts. They do
not select a player from season totals, betting odds or a prechosen Core.
"""
from copy import deepcopy

from nhl_true_blender_engine.engine import challenger_proof
from nhl_true_blender_engine.recent_origin import independently_bounded_origin_route
from nhl_true_blender_engine.tests.test_engine import skater


def _partially_unmapped(player, mapped=(1, 2)):
    data = player["recentOrigin"]["data"]
    zone = player["release"]["data"]["zone"]
    area = data["zoneCounts"][zone]
    old = area["byGame"]
    assert len(mapped) == len(old)
    area["byGame"] = [
        {**r, "shotsOnGoal": mapped[i],
         "ownedGoals": min(r["ownedGoals"], mapped[i])}
        for i, r in enumerate(old)
    ]
    area["shotsOnGoal"] = sum(mapped)
    area["ownedGoals"] = sum(x["ownedGoals"] for x in area["byGame"])
    data["sampleCoverageComplete"] = False
    data["unclassifiedOnNetShots"] = (
        sum(data["boxscoreShotsOnGoalByGame"].values()) - sum(mapped)
    )
    assert data["unclassifiedOnNetShots"] > 0
    return player


def _scene():
    candidate = skater(91501, "slot", 26, 2)
    rival = _partially_unmapped(skater(91502, "slot", 7, 1))
    return candidate, rival


def test_incomplete_location_sample_preserves_official_upper_not_zero():
    _, rival = _scene()
    result = independently_bounded_origin_route(rival, "slot")
    assert result["shotsOnGoalLowerBound"] == 3
    assert result["shotsOnGoalUpperBound"] == 7
    assert result["appearanceCount"] == 2
    assert result["completeExactOriginSample"] is False
    assert result["unknownLocationShotsMayBeInLane"] is True
    assert result["boundsAreOfficialDatedOnNetShots"] is True


def test_proven_lower_rate_defeats_unknown_location_upper_rate():
    candidate, rival = _scene()
    goalie = {"slot": {"savePct": 0.8}}
    winner, rows = challenger_proof(candidate, [rival], goalie, ["slot"])
    assert winner is True
    assert rows[0]["status"] == "DEFEATED"
    proof = rows[0]["independentRecentTieReview"]
    assert proof["result"] == "CANDIDATE"
    assert proof["missingShotLocationsNeverTreatedAsZero"] is True
    assert proof["candidateLowerCrossProduct"] > proof["rivalUpperCrossProduct"]
    loser, reverse = challenger_proof(rival, [candidate], goalie, ["slot"])
    assert loser is False
    assert reverse[0]["status"] == "RIVAL_DOMINATES"


def test_overlap_stays_unseparated_without_inventing_missing_rink_origins():
    candidate, rival = _scene()
    candidate = _partially_unmapped(candidate, mapped=(1, 1))
    goalie = {"slot": {"savePct": 0.8}}
    result, rows = challenger_proof(candidate, [rival], goalie, ["slot"])
    assert result is False
    assert rows[0]["status"] == "NO_DECISIVE_ROUTE_SEPARATION"
    bound = rows[0]["independentRecentTieReview"]
    assert bound["result"] == "UNSEPARATED"
    assert bound["candidate"]["shotsOnGoalUpperBound"] == 26


def test_unreconciled_pbp_boxscore_is_never_promoted_to_comparison():
    _, rival = _scene()
    corrupted = deepcopy(rival)
    corrupted["recentOrigin"]["data"]["pbpBoxscoreSogReconciled"] = False
    assert independently_bounded_origin_route(corrupted, "slot") is None
    corrupted = deepcopy(rival)
    corrupted["recentOrigin"]["data"]["boxscoreShotsOnGoalByGame"][
        corrupted["recentOrigin"]["data"]["sampleGameIds"][0]
    ] = 999
    assert independently_bounded_origin_route(corrupted, "slot") is None
