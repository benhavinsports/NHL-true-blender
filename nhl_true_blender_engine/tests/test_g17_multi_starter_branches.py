"""G17 checks every plausible projected starter, not only the first goalie.

Two independently reviewed identical scoring-lane branches are not inherently
contradictory. A second branch contradicting the scorer's own release stays open.
No goalie is promoted to confirmed and no Core is selected in this unit test.
"""
import json
from nhl_true_blender_engine.contradiction_review import review_all_candidates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_g17_source_review import build, ev, DATE


def _review_for_first_skater(tmp_path, second_goalie_weak_zones):
    snap=build()
    game=snap["games"][0]
    second={
        "goalieId":"100","status":"EXPECTED","team":"BOS",
        "weakZones":second_goalie_weak_zones,
        "strengthZones":{} if "Low Slot" in second_goalie_weak_zones
                          else {"Low Slot":{"shotsAgainst":60}},
        "sample":{"allZoneObservations":100},
        "counterevidence":{"unseparatedZones":["Point"]},
        "goalieProfileSourceUrl":"https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/100/now",
        "sourceType":"NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE",
        "anatomicalWeaknessCertified":False,
    }
    game["goalies"]["BOS"].append(ev("starter",100,second))
    con=open_db(str(tmp_path/"g17-multiple.sqlite"))
    try:
        review_all_candidates(con,snap,DATE,"PROJECTED")
        row=con.execute(
            "SELECT payload FROM evidence WHERE game_id='1000' AND player_id='1' "
            "AND kind='PLAYER_CONTRADICTIONS' ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        return json.loads(row["payload"])
    finally:
        con.close()


def test_two_independent_projected_starters_same_route_are_not_automatically_rejected(tmp_path):
    review=_review_for_first_skater(tmp_path,{"Low Slot":{"shotsAgainst":60}})
    goalie=review["goalieStrengthReview"]
    rivalry=review["strongestRivalReview"]
    assert goalie["opposingBranchesReviewed"]==2
    assert goalie["matchedWeakAreas"]==2
    assert goalie["everyStarterBranchMatched"] is True
    assert goalie["sameOwnOriginAcrossStarterBranches"] is True
    assert rivalry["everyRivalReviewed"] is True
    assert rivalry["eachSameLaneDefeated"] is True
    assert len(rivalry["perGoalieBranchReviews"])==2
    assert review["unresolved"] is False
    assert review["outcome"]=="CROSS_SOURCE_REVIEW_SATISFIED"


def test_alternate_projected_starter_with_no_matching_weak_origin_remains_unresolved(tmp_path):
    review=_review_for_first_skater(tmp_path,{"R Circle":{"shotsAgainst":60}})
    goalie=review["goalieStrengthReview"]
    assert goalie["opposingBranchesReviewed"]==2
    assert goalie["matchedWeakAreas"]==1
    assert goalie["everyStarterBranchMatched"] is False
    assert review["unresolved"] is True
    assert review["outcome"]=="UNRESOLVED_CONTRADICTION"
