"""Measured NHL EDGE shot-origin inference must be conservative and traceable."""
import json
from datetime import datetime,timezone
from nhl_true_blender_engine.storage import open_db,record_evidence
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.edge_derived_routes import (
    goalie_rink_weakness, skater_owned_routes, derive_nhl_edge_attacks,
    ORIGIN_METHOD, MIN_GOALIE_ZONE_SHOTS)
from nhl_true_blender_engine.engine import g0_full_slate, player_releases

DATE="2026-11-15"
def wrapper(pid,kind,areas):
    return {"sourceUrl":"https://api-web.nhle.com/v1/edge/"+kind+"-shot-location-detail/"+str(pid)+"/now",
            "observedAt":"2026-11-15T14:10:00+00:00",
            "data":{"scope":"NHL_EDGE_SHOT_ORIGIN_RINK_ONLY","rinkZoneRows":areas}}
def test_percentile_comparator_uses_real_save_and_shot_denominators():
    x=wrapper(88,"goalie",[
        {"area":"Low Slot","shotsAgainst":42,"goalsAgainst":8,"saves":34,
         "savePctgPercentile":.18},
        {"area":"High Slot","shotsAgainst":50,"goalsAgainst":1,"saves":49,
         "savePctgPercentile":.88},
        {"area":"R Circle","shotsAgainst":8,"goalsAgainst":3,"saves":5,
         "savePctgPercentile":.02}])
    review=goalie_rink_weakness(x)
    assert list(review["weakZones"])==["Low Slot"]
    assert list(review["strengthZones"])==["High Slot"]
    assert review["sample"]["qualifiedWeakZoneShots"]==42
    assert review["anatomicalWeaknessCertified"] is False
    assert review["counterevidence"]["otherAreas"]["High Slot"]["saves"]==49
def test_rejects_invented_or_inconsistent_shot_areas():
    x=wrapper(88,"goalie",[{"area":"Low Slot","shotsAgainst":30,"goalsAgainst":8,
                             "saves":25,"savePctgPercentile":.10}])
    assert goalie_rink_weakness(x)["weakZones"]=={}
    x["data"]["rinkZoneRows"][0]["saves"]=22
    x["data"]["rinkZoneRows"][0]["savePctgPercentile"]=None
    assert goalie_rink_weakness(x)["weakZones"]=={}
def test_skater_returns_source_owns_goal_not_assist_and_no_nonsense():
    x=wrapper(99,"skater",[
        {"area":"Low Slot","sog":19,"goals":3},
        {"area":"R Circle","sog":31,"goals":1}])
    p=skater_owned_routes(x)
    assert p["zone"]=="Low Slot"
    assert p["ownedGoals"]==3
    assert p["attempts"]==19
    assert p["isAnatomicalReleaseClaim"] is False
    assert p["isTotalShotAttempts"] is False
def test_underdetermined_tied_release_has_no_fake_favorite():
    x=wrapper(99,"skater",[
        {"area":"Low Slot","sog":9,"goals":2},
        {"area":"High Slot","sog":9,"goals":2}])
    assert skater_owned_routes(x)["canDeterminePrimary"] is False

def test_full_pool_derived_sources_attach_and_enable_real_g0_origin_scan(tmp_path):
    con=open_db(str(tmp_path/"test.sqlite"))
    url="https://example.org/starting-goalies"
    g={"id":"1000","date":DATE,"away":"NYR","home":"BOS",
       "goalies":{"BOS":[{"sourceUrl":url,"observedAt":"2026-11-15T14:10:00Z",
                            "data":{"goalieId":"88","team":"BOS","status":"EXPECTED"}}],
                  "NYR":[]},
       "rosters":{"NYR":{"sourceUrl":"https://api-web.nhle.com/v1/roster/NYR/current",
                           "observedAt":"2026-11-15T13:00:00Z",
                           "data":{"players":[{"id":"99","name":"Sample Shooter","position":"C"}]}},
                  "BOS":{"sourceUrl":"https://api-web.nhle.com/v1/roster/BOS/current",
                           "observedAt":"2026-11-15T13:00:00Z",
                           "data":{"players":[{"id":"77","name":"Another Shooter","position":"D"}]}}}}
    for pid,kind,zones in [
        ("88","NHL_EDGE_GOALIE_RINK_ORIGIN",[{"area":"Low Slot","shotsAgainst":42,
                 "saves":34,"goalsAgainst":8,"savePctgPercentile":.16}]),
        ("99","NHL_EDGE_SKATER_RINK_ORIGIN",[{"area":"Low Slot","sog":18,"goals":3}]),
        ("77","NHL_EDGE_SKATER_RINK_ORIGIN",[{"area":"High Slot","sog":10,"goals":1}])]:
        raw=wrapper(pid,"goalie" if pid=="88" else "skater",zones)
        record_evidence(con,{
            "evidence_id":"edge-"+pid,"slate_date":DATE,"stage":"PROJECTED",
            "game_id":"1000","player_id":pid,"kind":kind,
            "source_url":raw["sourceUrl"],"observed_at":raw["observedAt"],
            "payload":raw["data"]})
    snap={"games":[g]}
    result=derive_nhl_edge_attacks(con,snap,DATE,"PROJECTED")
    assert result["goalieProfilesWithMeasuredWeakOrigins"]==1
    assert result["ownSkaterRoutes"]==2
    assert result["anatomicalWeaknessCertified"] is False
    attach(con,snap,DATE,"PROJECTED")
    branches=g["goalies"]["BOS"]
    assert branches[0]["data"]["status"]=="EXPECTED"
    assert branches[0]["data"]["anatomicalWeaknessCertified"] is False
    assert branches[0]["data"]["weakZones"]["Low Slot"]["shotsAgainst"]==42
    assert player_releases(g["rosters"]["NYR"]["data"]["players"][0])["zone"]=="Low Slot"
    scan,errors=g0_full_slate([g],"PROJECTED")
    assert len(scan)==2 and scan[0]["goalieProfileEvidenced"] is True
    assert scan[1]["goalieProfileEvidenced"] is False
    count=con.execute("SELECT COUNT(*) FROM evidence WHERE kind='GOALIE_PROFILE'").fetchone()[0]
    assert count==1
    con.close()
