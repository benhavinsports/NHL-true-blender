"""G0: same-cohort official PBP where only ONE goalie has a weak origin.

Shape mirrors 2026020334 WSH@TBL on 2026-11-17: NHL EDGE worst-origin
percentiles tie exactly (0.1509 vs 0.1509), so EDGE cannot separate. In the
shared pre-slate PBP peer pool, one goalie is weak from two origins while the
other is source-reviewed with NO weak origin and better from both of those
same origins on goal rate AND peer rank. SYNTHETIC source-shaped inputs.
"""
import copy
from nhl_true_blender_engine.engine import (
    compare_g0_same_origin, compare_g0_different_weak_origins,
    compare_g0_shared_official_pbp, compare_g0_consensus_across_starters)

SRC = "https://api-web.nhle.com/v1/gamecenter/2026020011/play-by-play"
POP = "historical-source-cohort-1"
EDGE = "DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"


def row(shots, goals, rank):
    return {"shotsAgainst": shots, "goalsAgainst": goals,
            "samplePeerSavePctgPercentile": rank,
            "peerComparedSameOrigin": True, "peerGoaliesSampled": 38}


def cohort(pid, weak, observed, compared=None):
    return {"sourceUrl": SRC, "observedAt": "2026-11-17T13:01:21Z",
            "data": {"goalieId": pid,
                     "sourceClass": "INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY",
                     "samplePeerPopulationId": POP,
                     "peerSampleNeverLeagueEDGEPercentile": True,
                     "weakZones": weak, "observedAreas": observed,
                     "fullySourceComparedAreas": (len(observed) if compared is None
                                                  else compared)}}


def direction(attacker, defender, pid, edge_weak, peer):
    return {"gameId": "2026020334", "attacker": attacker, "defender": defender,
            "goalieProfileEvidenced": True,
            "targetGoalies": [{"goalieId": pid, "profileReviewed": True,
                               "sourceClass": EDGE, "sourceUrl": SRC,
                               "goalieProfileSourceUrl": SRC,
                               "weakZones": edge_weak, "sameCohortPbp": peer}]}


def nov17_shape():
    vasi_weak = {"L Circle": row(83, 8, .2439), "R Circle": row(92, 8, .2895)}
    vasi = cohort("8476883", vasi_weak, dict(vasi_weak))
    thompson_obs = {"L Circle": row(105, 7, .4878), "R Circle": row(84, 4, .7895),
                    "Low Slot": row(234, 43, .5846)}
    thompson = cohort("8480313", {}, thompson_obs)
    edge = lambda zone: {zone: {"shotsAgainst": 38, "goalsAgainst": 6,
                                "leagueSavePctgPercentile": .1509}}
    wsh = direction("WSH", "TBL", "8476883", edge("L Circle"), vasi)
    tbl = direction("TBL", "WSH", "8480313", edge("High Slot"), thompson)
    return wsh, tbl


def test_edge_exact_tie_does_not_choose():
    wsh, tbl = nov17_shape()
    assert compare_g0_same_origin(wsh, tbl) is None
    assert compare_g0_different_weak_origins(wsh, tbl) is None


def test_one_sided_pbp_weakness_resolves_direction_order_independently():
    wsh, tbl = nov17_shape()
    for a, b in ((wsh, tbl), (tbl, wsh)):
        chosen = compare_g0_shared_official_pbp(a, b)
        assert chosen is not None and chosen["attacker"] == "WSH"
        assert chosen["g0SelectionMethod"] == "SAME_HISTORICAL_OFFICIAL_PBP_ONE_SIDED_WEAKNESS"
        proof = chosen["g0DecisionProof"]
        assert proof["samePeerPopulationId"] == POP
        assert proof["exposedGoalieId"] == "8476883"
        assert [r["origin"] for r in proof["sameOriginComparisons"]] == ["L Circle", "R Circle"]
        assert compare_g0_consensus_across_starters(a, b)["attacker"] == "WSH"


def test_missing_same_origin_comparator_stays_unresolved():
    wsh, tbl = nov17_shape()
    del tbl["targetGoalies"][0]["sameCohortPbp"]["data"]["observedAreas"]["R Circle"]
    assert compare_g0_shared_official_pbp(wsh, tbl) is None
    assert compare_g0_consensus_across_starters(wsh, tbl) is None


def test_other_goalie_worse_on_either_measure_stays_unresolved():
    wsh, tbl = nov17_shape()
    worse_rate = copy.deepcopy(tbl)
    worse_rate["targetGoalies"][0]["sameCohortPbp"]["data"]["observedAreas"]["L Circle"] = row(105, 12, .4878)
    assert compare_g0_shared_official_pbp(wsh, worse_rate) is None
    worse_rank = copy.deepcopy(tbl)
    worse_rank["targetGoalies"][0]["sameCohortPbp"]["data"]["observedAreas"]["R Circle"] = row(84, 4, .20)
    assert compare_g0_shared_official_pbp(wsh, worse_rank) is None


def test_unreviewed_or_both_empty_profiles_never_choose():
    wsh, tbl = nov17_shape()
    unreviewed = copy.deepcopy(tbl)
    unreviewed["targetGoalies"][0]["sameCohortPbp"]["data"]["fullySourceComparedAreas"] = 0
    assert compare_g0_shared_official_pbp(wsh, unreviewed) is None
    both_empty = copy.deepcopy(wsh)
    both_empty["targetGoalies"][0]["sameCohortPbp"]["data"]["weakZones"] = {}
    assert compare_g0_shared_official_pbp(both_empty, tbl) is None


def test_different_population_never_chooses():
    wsh, tbl = nov17_shape()
    tbl["targetGoalies"][0]["sameCohortPbp"]["data"]["samplePeerPopulationId"] = "other"
    assert compare_g0_shared_official_pbp(wsh, tbl) is None
