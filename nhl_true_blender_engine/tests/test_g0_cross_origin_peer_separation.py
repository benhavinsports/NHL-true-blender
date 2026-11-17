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


def test_g0_core_replacement_rejects_identical_goalie_measurements(tmp_path):
    """New scrape time or CONFIRMED status is not new physical G0 evidence."""
    from datetime import datetime, timedelta, timezone
    from nhl_true_blender_engine.storage import open_db, save_card, record_evidence
    from nhl_true_blender_engine.engine import _material_g0_goalie_change
    db=open_db(str(tmp_path/"physical-source.sqlite"))
    date="2098-11-17"; game="9001"
    def profile(receipt_id,seen,goals,status="EXPECTED"):
        record_evidence(db,{
            "evidence_id":receipt_id,"slate_date":date,"stage":"PROJECTED",
            "game_id":game,"kind":"GOALIE_PROFILE",
            "source_url":"https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/10/now",
            "observed_at":seen.isoformat(),
            "payload":{"team":"TEAM_B","goalieId":"10","status":status,
                "weakZones":{"Low Slot":{"goalsAgainst":goals,"shotsAgainst":30,
                                          "leagueSavePctgPercentile":.11}}}})
    before=datetime.now(timezone.utc)-timedelta(hours=1)
    profile("baseline-profile",before,6)
    legs=[{"gameId":str(i),"playerId":str(i*10),
           "player":"Fixture scorer","path":"PRIMARY",
           "sourceIds":["https://api-web.nhle.com/v1/"],
           "startUTC":"2099-11-18T00:00:00Z","gameState":"FUT"}
          for i in (9001,9002,9003)]
    card=save_card(db,date,"PROJECTED",legs,3)
    try:
        # The very same weakness data with a new receipt, observed after card
        # issuance, cannot flip the previously saved G0 direction.
        profile("same-physical-profile",datetime.now(timezone.utc),6,"CONFIRMED")
        assert _material_g0_goalie_change(
            db,card,date,game,("same-physical-profile",)) is None

        # Only a changed numerical observation, from an independently saved
        # source, is material. The scorer is not chosen by this test.
        profile("new-physical-profile",datetime.now(timezone.utc),9,"CONFIRMED")
        changed=_material_g0_goalie_change(
            db,card,date,game,("new-physical-profile",))
        assert changed is not None
        assert changed["reason"]=="MEASURED_GOALIE_WEAK_ORIGIN_CHANGED"
        assert changed["priorEvidenceId"]=="baseline-profile"
        assert changed["triggerEvidenceId"]=="new-physical-profile"
    finally:
        db.close()


def test_g0_core_replacement_recognizes_new_confirmed_goalie_id(tmp_path):
    """An independently confirmed NEW starter is material, unlike a recheck."""
    from datetime import datetime, timedelta, timezone
    from nhl_true_blender_engine.storage import open_db, save_card, record_evidence
    from nhl_true_blender_engine.engine import _material_g0_goalie_change
    db=open_db(str(tmp_path/"new-starter.sqlite"))
    date="2098-11-18";game="9011"
    def entry(eid,kind,seen,goalie,status):
        record_evidence(db,{
          "evidence_id":eid,"slate_date":date,"stage":"PROJECTED",
          "game_id":game,"kind":kind,
          "source_url":"https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/11/now",
          "observed_at":seen.isoformat(),
          "payload":{"team":"TEAM_B","goalieId":goalie,"status":status,
                     "weakZones":{"Low Slot":{"goalsAgainst":6,"shotsAgainst":30}}}})
    entry("old-projection","GOALIE_STARTER",
          datetime.now(timezone.utc)-timedelta(hours=1),"11","EXPECTED")
    legs=[{"gameId":str(i),"playerId":str(i),
           "player":"Fixture scorer","path":"PRIMARY",
           "sourceIds":["https://api-web.nhle.com/v1/"],
           "startUTC":"2099-11-18T00:00:00Z","gameState":"FUT"}
          for i in (9011,9012,9013)]
    card=save_card(db,date,"PROJECTED",legs,3)
    try:
        entry("new-confirmed","GOALIE_STARTER",
              datetime.now(timezone.utc),"12","CONFIRMED")
        entry("new-confirmed-profile","GOALIE_PROFILE",
              datetime.now(timezone.utc),"12","CONFIRMED")
        change=_material_g0_goalie_change(
            db,card,date,game,("new-confirmed-profile",))
        assert change is not None
        assert change["reason"]=="NEW_CONFIRMED_STARTER_IDENTITY"
        assert change["priorStarterIds"]==["11"]
    finally:
        db.close()
