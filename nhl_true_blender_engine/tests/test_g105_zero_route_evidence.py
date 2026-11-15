"""Official EDGE zero-on-net is positive non-competitor evidence, not a fake G4 release."""
from nhl_true_blender_engine.storage import open_db,record_evidence
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.edge_derived_routes import derive_nhl_edge_attacks
from nhl_true_blender_engine.engine import challenger_proof

DATE="2026-11-15"
BASE="https://api-web.nhle.com/v1"
def sheet(pid,shots,goals):
    return {"evidence_id":f"edge-{pid}","slate_date":DATE,"stage":"PROJECTED",
        "game_id":"1001","player_id":str(pid),"kind":"NHL_EDGE_SKATER_RINK_ORIGIN",
        "source_url":f"{BASE}/edge/skater-shot-location-detail/{pid}/now",
        "observed_at":"2026-11-15T14:00:00Z",
        "payload":{"scope":"NHL_EDGE_SHOT_ORIGIN_RINK_ONLY",
            "rinkZoneRows":[{"area":"Low Slot","sog":shots,"goals":goals}]}}
def game():
    return {"id":"1001","away":"DAL","home":"FLA","goalies":{},"coverage":{},
        "rosters":{"DAL":{"data":{"players":[{"id":"100","name":"Proven Scorer","position":"C"},
                                           {"id":"200","name":"Zero Shot D","position":"D"}]}},
                   "FLA":{"data":{"players":[]}}}}
def source(pid,shots,goals):
    return {"sourceUrl":f"{BASE}/edge/skater-shot-location-detail/{pid}/now",
      "observedAt":"2026-11-15T14:00:00Z",
      "data":{"archetype":"OBSERVED_OWN_SHOT_ORIGIN","zone":"Low Slot",
              "attempts":shots,"ownedGoals":goals,
              "allRoutes":[{"zone":"Low Slot","sog":shots,"ownedGoals":goals}]}}
def test_nhl_edge_confirmed_zero_shot_teammate_is_recorded_not_fake_challenger(tmp_path):
    con=open_db(str(tmp_path/"state.sqlite"));g=game()
    record_evidence(con,sheet("100",24,4))
    record_evidence(con,sheet("200",0,0))
    stats=derive_nhl_edge_attacks(con,{"games":[g]},DATE,"PROJECTED")
    assert stats["sourceVerifiedZeroShotRivalProfiles"]==1
    attach(con,{"games":[g]},DATE,"PROJECTED")
    players=g["rosters"]["DAL"]["data"]["players"]
    assert players[1].get("release") is None
    assert players[1]["zeroShotOriginProof"]["data"]["verifiedNoSameLaneOnNetRoute"] is True
    won,details=challenger_proof(players[0],[players[1]],{"Low Slot":{}})
    assert won is True
    assert details[0]["status"]=="SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE"
    assert details[0]["sourceUrls"]==[f"{BASE}/edge/skater-shot-location-detail/200/now"]
    assert details[0]["noClaimOfFutureScoringImpossibility"] is True
    con.close()

def test_missing_source_without_evidenced_zero_is_still_unresolved():
    p={"id":"100","release":source(100,24,4)}
    missing={"id":"200"}
    won,details=challenger_proof(p,[missing],{"Low Slot":{}})
    assert won is False
    assert details[0]["status"]=="NO_RELEASE_SOURCE"
