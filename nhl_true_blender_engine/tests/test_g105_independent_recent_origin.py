"""Source-backed G10.5 season ties require independent dated own-goal routes."""
from nhl_true_blender_engine.engine import challenger_proof
from nhl_true_blender_engine.historical_shots import measured_recent_shooter_origins
from nhl_true_blender_engine.tests.test_engine import skater,evidence

URL="https://api-web.nhle.com/v1/gamecenter/2026020134/play-by-play"

def recent(goals,shots):
    return evidence({"sourceType":"OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN",
        "scope":"RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY",
        "rinkBinsApproximateNotNhlEdgePolygons":True,
        "historicalOwnGoalCreditOnly":True,
        "zoneCounts":{"High Slot":{"shotsOnGoal":shots,"ownedGoals":goals,
            "sourceUrls":[URL],"gameIds":["2026020134"]}}},source=URL)

def tied():
    a=skater(700,"High Slot",5,2)
    b=skater(701,"High Slot",5,2)
    return a,b

def test_recent_direct_nhl_pbp_scoring_can_distinguish_actual_season_route_tie():
    a,b=tied()
    a["recentOrigin"]=recent(2,4)
    b["recentOrigin"]=recent(0,5)
    wins,rows=challenger_proof(a,[b],{"High Slot":{}},["High Slot"])
    assert wins is True
    assert rows[0]["status"]=="DEFEATED"
    assert rows[0]["independentRecentTieReview"]["own"]["ownedGoals"]==2
    assert URL in rows[0]["sourceUrls"]
    other,opposite=challenger_proof(b,[a],{"High Slot":{}},["High Slot"])
    assert other is False
    assert opposite[0]["status"]=="RIVAL_DOMINATES"

def test_missing_or_same_recent_proof_never_manufactures_direct_recipient():
    a,b=tied()
    a["recentOrigin"]=recent(2,4)
    b.pop("recentOrigin",None)
    wins,rows=challenger_proof(a,[b],{"High Slot":{}},["High Slot"])
    assert wins is False and rows[0]["status"]=="UNRESOLVED_RECENT_DIRECT_ROUTE_EVIDENCE"
    b["recentOrigin"]=recent(2,4)
    wins,rows=challenger_proof(a,[b],{"High Slot":{}},["High Slot"])
    assert wins is False and rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"

def test_exact_official_goal_not_assist_and_no_duplicate_on_net_origin():
    events=[{"gameId":"2026020134","eventId":"1","shooterId":"700",
        "type":"goal","x":60,"y":3,"sourceUrl":URL},
        {"gameId":"2026020134","eventId":"1","shooterId":"700",
        "type":"goal","x":60,"y":3,"sourceUrl":URL},
        {"gameId":"2026020134","eventId":"2","shooterId":"700",
        "type":"shot-on-goal","x":60,"y":3,"sourceUrl":URL},
        {"gameId":"2026020134","eventId":"3","shooterId":"700",
        "type":"missed-shot","x":60,"y":3,"sourceUrl":URL},
        {"gameId":"2026020134","eventId":"4","shooterId":"701",
        "type":"goal","x":60,"y":3,"sourceUrl":URL}]
    area=measured_recent_shooter_origins(events,"700")["High Slot"]
    assert area["shotsOnGoal"]==2
    assert area["ownedGoals"]==1
    assert area["sourceUrls"]==[URL]
