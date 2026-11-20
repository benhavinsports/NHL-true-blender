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
    p1["pressure"]=ev("shots",1,{"recentAppearanceShots":[3,4,3],
        "appearances":[{"date":"2026-11-11"},{"date":"2026-11-12"},{"date":"2026-11-13"}]})
    p2={"id":"2","name":"Shooter 2","position":"D",
        "availability":"PROJECTED_ACTIVE",
        "release":ev("edge",2,{"archetype":"OBSERVED_OWN_SHOT_ORIGIN",
            "zone":"High Slot","attempts":19,"ownedGoals":2,
            "allRoutes":[{"zone":"High Slot","sog":19,"ownedGoals":2},
                         {"zone":"Low Slot","sog":18 if not better_rival else 45,
                          "ownedGoals":3 if not better_rival else 11}]})}
    p2["deployment"]=ev("lines",2,{"EV":"D2","status":"PROJECTED"})
    p2["pressure"]=ev("shots",2,{"recentAppearanceShots":[1,2,1],
        "appearances":[{"date":"2026-11-11"},{"date":"2026-11-12"},{"date":"2026-11-13"}]})
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


def test_resolved_nonanatomical_derived_review_is_certifiable_without_faking_glove_weakness():
    # The G17 collector only obtains NHL EDGE shot-ORIGIN profiles; prior
    # certification mistakenly insisted on a nonexistent anatomical map.
    from nhl_true_blender_engine.semantic_certification import audit_gate
    c={
        "sourceType":SCOPE,"unresolved":False,
        "scope":"observed shot origins, NOT anatomical goal-mouth coordinates",
        "anatomicalWeaknessCertified":False,
        "goalieStrengthReview":{
            "sourceScope":"GOALIE_SHOT_ORIGIN_VS_SHOOTER_OWN_AREA",
            "matchedWeakAreas":1,"strongerAreaContradiction":False,
            "opposingBranchesReviewed":1},
        "lineupDisagreementReview":{
            "hasProjectedOrConfirmedRole":True,"isTrulyConfirmed":False},
        "strongestRivalReview":{
            "everyRivalReviewed":True,"eachSameLaneDefeated":True},
    }
    e={"counterevidence":c,"sourceDerivedReviewResolved":True,
       "retainsConflictingSources":True}
    source=["https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/99/now"]
    assert audit_gate("G17",e,source,"PROJECTED")==[]
    bad={**c,"unresolved":True}
    assert "G17_STRUCTURED_CONTRADICTION_REVIEW_NOT_RESOLVED" in audit_gate(
        "G17",{**e,"counterevidence":bad,"sourceDerivedReviewResolved":False},
        source,"PROJECTED")
    contradictory={**c,"goalieStrengthReview":{
        **c["goalieStrengthReview"],"strongerAreaContradiction":True}}
    assert "G17_OBSERVED_GOALIE_STRENGTH_CONTRADICTION_NOT_CLEARED" in audit_gate(
        "G17",{**e,"counterevidence":contradictory},source,"PROJECTED")
    not_independently_sourced={**c,"goalieStrengthReview":{
        "sourceScope":"UNKNOWN","matchedWeakAreas":0,
        "strongerAreaContradiction":False}}
    faults=audit_gate("G17",{**e,"counterevidence":not_independently_sourced},
                     source,"PROJECTED")
    assert "G17_RINK_ORIGIN_SCOPE_MISREPRESENTED" in faults
    assert "G17_OBSERVED_GOALIE_STRENGTH_CONTRADICTION_NOT_CLEARED" in faults


def test_g17_uses_identical_g0_g9_goalie_defense_rival_scope_as_g105(tmp_path):
    """A better rival in a goalie-weak but G9-defended zone cannot secretly
    veto the G10.5 winner when G17 rechecks the SAME pregame direct routes.
    """
    con=open_db(str(tmp_path/"same-route.sqlite"))
    slate=build()
    game=slate["games"][0]
    game["goalies"]["BOS"][0]["data"]["weakZones"]["High Slot"]={"shotsAgainst":31}
    rival=game["rosters"]["NYR"]["data"]["players"][1]
    rival["release"]["data"].update({
        "zone":"High Slot","attempts":24,"ownedGoals":11,
        "allRoutes":[{"zone":"High Slot","sog":24,"ownedGoals":11},
                     {"zone":"Low Slot","sog":18,"ownedGoals":3}]
    })
    game["coverage"]={"NYR":ev("coverage","NYR",{
        "greenWeakZones":["Low Slot"],
        "redStrongZones":["High Slot"]})}
    result=review_all_candidates(con,slate,DATE,"PROJECTED")
    assert result["reviewedSkaters"]==2
    original=con.execute("""SELECT payload FROM evidence
        WHERE player_id='1' AND kind='PLAYER_CONTRADICTIONS'""").fetchone()
    data=json.loads(original["payload"])
    assert data["unresolved"] is False
    assert data["strongestRivalReview"]["eachSameLaneDefeated"] is True
    assert data["strongestRivalReview"]["matchesG10_5GoalieAndDefenseRouteScope"] is True
    assert data["strongestRivalReview"]["G9OpponentDefenseWeakZonesUsed"]==["Low Slot"]
    rival_proof=data["strongestRivalReview"]["rivalResults"][0]
    assert rival_proof["status"]=="DEFEATED"
    assert rival_proof["challenger"]["zone"]=="Low Slot"
    assert rival_proof["goalieWeaknessAndDefenseBothRequired"] is True
    con.close()
