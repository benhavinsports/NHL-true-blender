"""Final choice must come from all gates passing plus real comparable source receipts."""
from nhl_true_blender_engine.engine import (
    g18_source_vector,g18_select_by_evidence,cross_game_winners)

URL="https://api-web.nhle.com/v1"
def receipt(data,url):
    return {"sourceUrl":url,"observedAt":"2026-11-15T16:00:00Z","data":data}
def finalist(gid,pid,zone,own_goals,own_shots,percentile,def_share):
    own={"archetype":"OBSERVED_OWN_SHOT_ORIGIN","zone":zone,
         "ownedGoals":own_goals,"attempts":own_shots}
    target={"goalieId":"goalie-"+str(gid),"status":"EXPECTED",
            "weakZones":{zone:{"shotsAgainst":50,"goalsAgainst":10,
                               "leagueSavePctgPercentile":percentile}},
            "goalieProfileSourceUrl":URL+"/edge/goalie-shot-location-detail/88/now"}
    coverage={
        "sourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
        "comparison":"RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN",
        "lowShotVolumeIsNotEvidenceOfDefensiveStrength":True,
        "greenWeakZones":[zone],
        "zoneConcessions":{zone:{
            "attemptsAgainst":36,"gameCount":8,"peerTeamsCompared":20,
            "attemptsPerGame":def_share*20,
            "peerMedianAttemptsPerGame":2.0}}}
    player={"id":str(pid),"name":"Fixture skater "+str(pid),
            "release":receipt(own,URL+"/edge/skater-shot-location-detail/99/now"),
            "deployment":receipt({"EV":"F2","status":"PROJECTED"},
                                 URL+"/roster/DET/current")}
    return {"game":{"id":str(gid),"coverage":{"DET":receipt(
           coverage,URL+"/gamecenter/1/play-by-play")}},
            "attackTeam":"DET","targetGoalie":receipt(target,URL+"/roster/CHI/current"),
            "candidate":{"player":player,"release":own,"route":"PRIMARY"}}

def test_source_proven_two_finalists_same_game_select_one_direct_recipient():
    a=finalist(100,1,"Low Slot",4,22,.12,.25)
    b=finalist(100,2,"L Circle",2,14,.06,.31)
    winners,errors,audit=g18_select_by_evidence([a,b],1,"one game")
    assert not errors
    assert len(winners)==1
    assert winners[0] is a
    assert len(audit)==2
    assert audit[0]["selection"]=="G18_SELECTED"
    assert audit[1]["selection"]=="G18_SOURCE_SEPARATED"
    assert len(audit[0]["sourceUrls"])==4
    assert audit[0]["notAMarketOrChalkScore"] is True

def test_five_source_separated_games_yield_exact_three_no_bogus_same_game():
    eligible=[
        finalist(100,1,"Low Slot",1,20,.03,.23),
        finalist(200,2,"L Circle",5,32,.05,.21),
        finalist(300,3,"Low Slot",4,28,.06,.18),
        finalist(400,4,"High Slot",2,19,.04,.24),
        finalist(500,5,"Low Slot",3,23,.09,.29)]
    chosen,errors=cross_game_winners(eligible,5)
    assert not errors
    assert len(chosen)==3
    assert {x["candidate"]["player"]["id"] for x in chosen}=={"2","3","5"}
    assert len({x["game"]["id"] for x in chosen})==3

def test_exact_tie_at_third_slot_requires_more_real_evidence_not_name_tiebreak():
    entries=[finalist(100,1,"Low Slot",5,20,.03,.20),
             finalist(200,2,"Low Slot",4,20,.03,.20),
             finalist(300,3,"Low Slot",2,20,.03,.20),
             finalist(400,4,"Low Slot",2,20,.03,.20)]
    choice,errors=cross_game_winners(entries,4)
    assert not choice and "tied" in str(errors)

def test_missing_independent_goalie_or_team_comparator_cannot_force_arbitrary_three():
    entries=[finalist(i,i,"Low Slot",i,20,.05,.25) for i in range(1,5)]
    del entries[3]["targetGoalie"]["data"]["weakZones"]["Low Slot"]["leagueSavePctgPercentile"]
    chosen,errors=cross_game_winners(entries,4)
    assert not chosen and "evidence missing" in str(errors)


def test_g18_rejects_obsolete_share_only_coverage_even_if_candidate_claims_pass():
    """Source schema must agree with G9; a cosmetic label cannot qualify."""
    item=finalist(100,1,"Low Slot",3,20,.05,.25)
    data=item["game"]["coverage"]["DET"]["data"]
    data["comparison"]="RECENT_OPPONENT_SHOT_ORIGIN_SHARES_AGAINST_PEER_MEDIAN"
    data["zoneConcessions"]["Low Slot"]={"share":.25,"peerMedianShare":.10}
    assert g18_source_vector(item) is None


def test_g18_missing_actual_per_game_defensive_source_cannot_force_a_core():
    items=[finalist(i,i,"Low Slot",i,20,.05,.24) for i in range(1,5)]
    del items[-1]["game"]["coverage"]["DET"]["data"]["zoneConcessions"]["Low Slot"]["attemptsPerGame"]
    winners,errors=cross_game_winners(items,4)
    assert winners==[]
    assert "evidence missing" in str(errors)


def test_g18_peer_and_attempt_finite_thresholds_not_fake_sorting():
    item=finalist(100,1,"Low Slot",3,20,.05,.25)
    assert g18_source_vector(item) is not None
    detail=item["game"]["coverage"]["DET"]["data"]["zoneConcessions"]["Low Slot"]
    detail["peerTeamsCompared"]=2
    assert g18_source_vector(item) is None
    detail["peerTeamsCompared"]=10
    detail["attemptsPerGame"]=float("nan")
    assert g18_source_vector(item) is None
