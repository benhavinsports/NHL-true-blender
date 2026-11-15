"""G0 physical origin review must show BOTH expected and confirmed branches without upgrading status."""
from nhl_true_blender_engine.storage import open_db,record_evidence
from nhl_true_blender_engine.edge_live import review_g0_goalie_origins
from nhl_true_blender_engine.tests.test_engine import DATE, SRC

def test_g0_origin_review_keeps_unconfirmed_goalies_and_two_directions(tmp_path):
    db=open_db(str(tmp_path/"r.sqlite"))
    g={"id":"5001","away":"NYR","home":"BOS",
       "goalies":{"NYR":[{"sourceUrl":SRC,"observedAt":"2026-11-15T12:00:00Z",
                            "data":{"team":"NYR","goalieId":"88","status":"EXPECTED"}}],
                  "BOS":[{"sourceUrl":SRC,"observedAt":"2026-11-15T12:00:00Z",
                            "data":{"team":"BOS","goalieId":"99","status":"CONFIRMED"}}]}}
    for pid in ("88","99"):
        record_evidence(db,{
            "evidence_id":"edge-"+pid,"slate_date":DATE,"stage":"CONFIRMED",
            "kind":"NHL_EDGE_GOALIE_RINK_ORIGIN","game_id":"5001","player_id":pid,
            "source_url":SRC,"observed_at":"2026-11-15T12:00:00Z",
            "payload":{"rinkZoneRows":[{"area":"Low Slot","shotsAgainst":45,"goalsAgainst":7,
                "savePctg":38/45,"savePctgPercentile":0.22}]}})
    result=review_g0_goalie_origins(db,{"games":[g]},DATE,"CONFIRMED")
    assert len(result)==1 and len(result[0]["directions"])==2
    left,right=result[0]["directions"]
    assert left["goalieBranches"][0]["starterStatus"]=="CONFIRMED"
    assert right["goalieBranches"][0]["starterStatus"]=="EXPECTED"
    assert left["goalieBranches"][0]["zoneProfileFound"] is True
    assert right["goalieBranches"][0]["zoneProfileFound"] is True
    assert result[0]["anatomicalWeaknessCertified"] is False
    db.close()
