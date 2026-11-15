"""G17 must examine actual goalie strength, EV role and every direct challenger."""
import json
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.contradiction_review import review_all_candidates,SCOPE
from nhl_true_blender_engine.engine import receipt

URL="https://api-web.nhle.com/v1/"
DATE="2026-11-15"
def ev(kind,ident,data):
    return {"sourceUrl":URL+kind+"/"+str(ident),"observedAt":"2026-11-15T13:00:00Z",
            "data":data}

def build(deployment=True,better_rival=False):
    p1={"id":"1","name":"Shooter 1","position":"C",
        "availability":"PROJECTED_ACTIVE",
        "release":ev("edge",1,{"archetype":"OBSERVED_OWN_SHOT_ORIGIN",
            "zone":"Low Slot","attempts":36,"ownedGoals":8,
            "allRoutes":[{"zone":"Low Slot","sog":36,"ownedGoals":8}]})}
    if deployment:
        p1["deployment"]=ev("lines",1,{"EV":"F1","status":"PROJECTED"})
    p2={"id":"2","name":"Shooter 2","position":"D",
        "availability":"PROJECTED_ACTIVE",
        "release":ev("edge",2,{"archetype":"OBSERVED_OWN_SHOT_ORIGIN",
            "zone":"High Slot","attempts":19,"ownedGoals":2,
            "allRoutes":[{"zone":"High Slot","sog":19,"ownedGoals":2},
                         {"zone":"Low Slot","sog":18 if not better_rival else 45,
                          "ownedGoals":3 if not better_rival else 11}]})}
    goalie={"goalieId":"99","status":"EXPECTED","team":"BOS",
        "weakZones":{"Low Slot":{"shotsAgainst":42}},
        "strengthZones":{"High Slot":{"shotsAgainst":65}},
        "sample":{"allZoneObservations":100},
        "counterevidence":{"unseparatedZones":["Point"]},
        "goalieProfileSourceUrl":URL+"edge/goalie/99",
        "sourceType":"NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE",
        "anatomicalWeaknessCertified":False}
    game={"id":"1000","date":DATE,"away":"NYR","home":"BOS",
          "goalies":{"BOS":[ev("starter",99,goalie)],"NYR":[]},
          "rosters":{"NYR":ev("roster","NYR",{"players":[p1,p2]}),
                     "BOS":ev("roster","BOS",{"players":[]})}}
    return {"games":[game]}

def test_direct_source_review_resolves_only_when_every_challenger_defeated(tmp_path):
    con=open_db(str(tmp_path/"g17.sqlite"))
    result=review_all_candidates(con,build(),DATE,"PROJECTED")
    assert result["reviewedSkaters"]==2
    row=con.execute("SELECT payload FROM evidence WHERE player_id='1' AND kind='PLAYER_CONTRADICTIONS'").fetchone()
    data=json.loads(row["payload"])
    assert data["sourceType"]==SCOPE
    assert data["unresolved"] is False
    assert data["goalieStrengthReview"]["matchedWeakAreas"]==1
    assert data["strongestRivalReview"]["eachSameLaneDefeated"] is True
    assert data["lineupDisagreementReview"]["isTrulyConfirmed"] is False
    con.close()

def test_source_review_cannot_assert_no_contradiction_without_lineup_or_on_rival_dominance(tmp_path):
    con=open_db(str(tmp_path/"g17bad.sqlite"))
    review_all_candidates(con,build(deployment=False,better_rival=True),DATE,"PROJECTED")
    row=con.execute("SELECT payload FROM evidence WHERE player_id='1' AND kind='PLAYER_CONTRADICTIONS'").fetchone()
    data=json.loads(row["payload"])
    assert data["unresolved"] is True
    assert data["lineupDisagreementReview"]["hasProjectedOrConfirmedRole"] is False
    assert data["strongestRivalReview"]["eachSameLaneDefeated"] is False
    con.close()
