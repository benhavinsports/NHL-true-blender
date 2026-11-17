"""Two verified G0 goalie weaknesses from distinct areas can still be compared.

These measured save-percentile values are source-shaped synthetic fixtures;
they are NOT asserted to be live NHL results.
"""
from nhl_true_blender_engine.engine import compare_g0_different_weak_origins

EDGE="DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"
PBP="INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY"
URL="https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/"

def direction(attacker,defender,zone,percentile,shots,goals,typ=EDGE):
    col="leagueSavePctgPercentile" if typ==EDGE else "samplePeerSavePctgPercentile"
    goalie={"goalieId":defender+"-goalie","sourceClass":typ,
       "sourceUrl":URL+str(100+len(defender))+"/now",
       "goalieProfileSourceUrl":URL+str(200+len(defender))+"/now",
       "profileReviewed":True,
       "weakZones":{zone:{col:percentile,"shotsAgainst":shots,
                           "goalsAgainst":goals,
                           "sourceUrl":URL+str(123+len(defender))+"/now"}}}
    return {"attacker":attacker,"defender":defender,"targetGoalies":[goalie],
            "goalieProfileEvidenced":True}

def test_distinct_rink_origin_weaknesses_select_lowest_normalized_nhl_peer_rank():
    # Two independent goalies exhibit verified weaknesses in different
    # areas: a strict set-equality comparison would falsely never select.
    a=direction("MTL","NYR","L Point",.1379,36,3)
    b=direction("NYR","MTL","Center Point",.3103,24,2)
    choice=compare_g0_different_weak_origins(a,b)
    assert choice is not None
    assert choice["attacker"]=="MTL"
    assert choice["defender"]=="NYR"
    assert choice["g0SelectedOnlyAfterBothStarterProfiles"] is True
    assert choice["g0SelectionMethod"]=="NHL_EDGE_SOURCE_PEER_PERCENTILE_CROSS_ORIGIN_G0"
    assert choice["g0DecisionProof"]["winnerWeakOrigin"]=="L Point"
    assert choice["g0DecisionProof"]["oppositeWeakOrigin"]=="Center Point"
    assert choice["g0DecisionProof"]["noWeightsOrExternalOdds"] is True

def test_distinct_origin_can_choose_other_direction_without_home_chalk_bias():
    a=direction("VAN","UTA","L Circle",.0862,44,8)
    b=direction("UTA","VAN","Outside R",.0517,23,4)
    choice=compare_g0_different_weak_origins(a,b)
    assert choice["attacker"]=="UTA"
    assert choice["g0DecisionProof"]["winnerGoalsAllowedFromOrigin"]==4
    assert choice["g0DecisionProof"]["winnerGoaliePeerSavePercentile"]==.0517

def test_tied_peers_cannot_use_goalie_name_venue_or_sample_volume_tiebreaker():
    a=direction("A","B","L Circle",.16,40,4)
    b=direction("B","A","High Slot",.16,30,3)
    assert compare_g0_different_weak_origins(a,b) is None

def test_missing_weak_origin_source_or_incomplete_peer_denominator_never_picks():
    a=direction("A","B","L Circle",.10,40,4)
    b=direction("B","A","High Slot",.22,13,2)
    assert compare_g0_different_weak_origins(a,b) is None
    b["targetGoalies"][0]["weakZones"]["High Slot"]["shotsAgainst"]=40
    b["targetGoalies"][0]["profileReviewed"]=False
    assert compare_g0_different_weak_origins(a,b) is None

def test_edge_league_percentile_cannot_be_compared_to_sample_local_peer_percentile():
    a=direction("A","B","L Circle",.10,40,4,EDGE)
    b=direction("B","A","High Slot",.20,40,4,PBP)
    assert compare_g0_different_weak_origins(a,b) is None

def test_local_historical_pbp_peers_must_be_compared_only_with_same_method():
    a=direction("A","B","L Circle",.08,45,8,PBP)
    b=direction("B","A","High Slot",.23,40,5,PBP)
    comparison=compare_g0_different_weak_origins(a,b)
    assert comparison["attacker"]=="A"
    assert comparison["g0SelectionMethod"]=="NHL_PBP_SAMPLED_PEER_RANK_CROSS_ORIGIN_G0"


def test_equal_rounded_edge_peer_percentile_is_not_equal_actual_scoring_vulnerability():
    # Independently measured official goalie-area shots vs own goals:
    # published lowest league-percentile ties, but integer goal fractions
    # differ. This is an additional physical goalie observation, not a
    # fabricated tie-breaker, scorer weight, or market favorite.
    a=direction("WSH","TBL","L Circle",.1509,38,6)
    b=direction("TBL","WSH","High Slot",.1509,31,7)
    choice=compare_g0_different_weak_origins(a,b)
    assert choice is not None
    assert choice["attacker"]=="TBL"
    assert choice["g0SelectionMethod"]=="TIED_PUBLISHED_PEER_PERCENTILE_DIRECT_OBSERVED_GOAL_RATE"
    assert choice["g0DecisionProof"]["publishedEqualPeerSavePercentile"]==.1509
    assert choice["g0DecisionProof"]["directRateComparedByExactIntegerCrossProduct"] is True
    assert choice["g0DecisionProof"]["winnerGoalsAllowedFromOrigin"]==7

def test_exact_empirical_tie_or_multiple_tied_weak_origins_remains_unresolved():
    a=direction("WSH","TBL","L Circle",.1509,38,6)
    b=direction("TBL","WSH","High Slot",.1509,31,7)
    b["targetGoalies"][0]["weakZones"]["R Circle"]={
      "leagueSavePctgPercentile":.1509,"shotsAgainst":44,"goalsAgainst":8}
    assert compare_g0_different_weak_origins(a,b) is None
    b["targetGoalies"][0]["weakZones"].pop("R Circle")
    b["targetGoalies"][0]["weakZones"]["High Slot"]["goalsAgainst"]=3
    b["targetGoalies"][0]["weakZones"]["High Slot"]["shotsAgainst"]=19
    assert compare_g0_different_weak_origins(a,b) is None
