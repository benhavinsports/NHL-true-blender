"""Regression: G16 uses the actual G0 PBP fallback and both G9 methods.

These are source-shaped synthetic receipts. They are not certified live picks.
Historical scoring totals may be logged but never decide a comparison.
"""
from nhl_true_blender_engine.engine import g16_cross_game_finalists
from nhl_true_blender_engine.tests.test_g16_cross_game_finalists import matched_finalist


def test_fixed_same_population_pbp_percentile_compares_without_edge_alias():
    rows = [
        matched_finalist(1, "a", 1, 11, .05, 2.0),
        matched_finalist(2, "b", 2, 12, .10, 1.9),
        matched_finalist(3, "c", 3, 13, .15, 1.8),
        matched_finalist(4, "d", 14, 24, .85, 1.1),
    ]
    for i, item in enumerate(rows):
        zone=item["candidate"]["release"]["zone"]
        z=item["targetGoalie"]["data"]["weakZones"][zone]
        z["samplePeerSavePctgPercentile"]=z.pop("leagueSavePctgPercentile")
        z["peerGoaliesSampled"]=12
        item["targetGoalie"]["data"]["samplePeerPopulationId"]="observed-fixed-cohort"
        item["targetGoalie"]["data"]["samplePeerPopulationStable"]=True
    selected, receipt = g16_cross_game_finalists(rows,3)
    assert [z["candidate"]["player"]["id"] for z in selected]==["a","b","c"]
    assert receipt["excludedPlayerIds"]==["d"]
    assert all(z["g16ComparisonBasis"].startswith("OFFICIAL_PBP_STABLE_PEERS:")
               for z in receipt["finalists"])
    rows[3]["targetGoalie"]["data"]["samplePeerPopulationId"]="different-cohort"
    selected, receipt = g16_cross_game_finalists(rows,3)
    assert len(selected)==4
    assert receipt["separated"] is False
    rows[3]["targetGoalie"]["data"]["samplePeerPopulationStable"]=False
    selected, receipt = g16_cross_game_finalists(rows,3)
    assert len(selected)==4
    assert receipt["finalists"][3]["g16ComparisonBasis"]=="NOT_COMPARABLE"


def test_qualified_attempts_only_defense_still_advances_without_on_net_override():
    rows=[
        matched_finalist(1,"a",1,11,.05,2.0),
        matched_finalist(2,"b",2,12,.10,1.9),
        matched_finalist(3,"c",3,13,.15,1.8),
        matched_finalist(4,"d",14,24,.85,1.1),
    ]
    for i,item in enumerate(rows):
        zone=item["candidate"]["release"]["zone"]
        detail=item["game"]["coverage"]["AWAY"]["data"]["zoneConcessions"][zone]
        detail.update({
            "attemptsPerGame":[12.0,11.5,11.0,9.0][i],
            "peerMedianAttemptsPerGame":8,
            "onNetShotsPerGame":7,
            "peerMedianOnNetShotsPerGame":8,
            "positiveConcessionBases":["ATTEMPTS_AGAINST_PEER"],
        })
    selected,receipt=g16_cross_game_finalists(rows,3)
    assert [z["candidate"]["player"]["id"] for z in selected]==["a","b","c"]
    assert receipt["excludedPlayerIds"]==["d"]
    assert all("G9_OFFICIAL_ATTEMPTS_VS_PEERS" in z["g16ComparisonBasis"]
               for z in receipt["finalists"])
    # An on-net-only finalist cannot be compared to attempts-only finalists.
    detail=rows[3]["game"]["coverage"]["AWAY"]["data"]["zoneConcessions"]["Low Slot"]
    detail.update({"onNetShotsPerGame":12,"positiveConcessionBases":["ON_NET_SHOTS_AGAINST_PEER"]})
    selected,receipt=g16_cross_game_finalists(rows,3)
    assert len(selected)==4
    assert receipt["separated"] is False


def test_dual_method_route_uses_shared_attempts_against_attempt_only_rivals():
    # All goalie values use the SAME NHL EDGE cohort. The first three games
    # have G9 positive on-net plus attempts; the fourth has only attempts.
    # G16 must not refuse to compare because its preferred evidence differs.
    rows=[
        matched_finalist(1,"a",1,11,.05,2.0),
        matched_finalist(2,"b",2,12,.10,1.9),
        matched_finalist(3,"c",3,13,.15,1.8),
        matched_finalist(4,"d",14,24,.85,1.1),
    ]
    for i, row in enumerate(rows):
        z=row["candidate"]["release"]["zone"]
        proof=row["game"]["coverage"]["AWAY"]["data"]["zoneConcessions"][z]
        proof.update({"attemptsPerGame":[15,14,13,9][i],
                      "peerMedianAttemptsPerGame":8,
                      "positiveConcessionBases":(
                          ["ATTEMPTS_AGAINST_PEER","ON_NET_SHOTS_AGAINST_PEER"]
                          if i<3 else ["ATTEMPTS_AGAINST_PEER"]),
                      "onNetShotsPerGame":7 if i==3 else [12,11,10][i],
                      "peerMedianOnNetShotsPerGame":8})
    selected,receipt=g16_cross_game_finalists(rows,3)
    assert [x["candidate"]["player"]["id"] for x in selected]==["a","b","c"]
    fourth=receipt["finalists"][3]
    assert sorted(fourth["dominatedBy"])==["a","b","c"]
    assert set(fourth["dominatedBySharedMethods"].values())=={
        "G9_OFFICIAL_ATTEMPTS_VS_PEERS"}
    assert all(len(r["g16AvailableDefenseMethods"])==2
               for r in receipt["finalists"][:3])
