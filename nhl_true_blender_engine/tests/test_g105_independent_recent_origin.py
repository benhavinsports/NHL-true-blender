"""Recent own goals cannot break a tie; dated same-lane shot rates can."""
from nhl_true_blender_engine.engine import challenger_proof
from nhl_true_blender_engine.historical_shots import measured_recent_shooter_origins
from nhl_true_blender_engine.tests.test_engine import skater,evidence,DATE,SRC

URL="https://api-web.nhle.com/v1/gamecenter/2026020134/play-by-play"


def recent(player,goals,shots_by_game):
    pressure=player["pressure"]["data"]
    appearances=pressure["appearances"]
    ids=[str(x["gameId"]) for x in appearances]
    dates=[x["date"] for x in appearances]
    goal_counts=list(goals if isinstance(goals,list) else [goals]+[0]*(len(ids)-1))
    by_game=[{"gameId":ids[i],"date":dates[i],
              "shotsOnGoal":shots_by_game[i],"ownedGoals":goal_counts[i],
              "sourceUrls":[URL]} for i in range(len(ids))]
    zone=player["release"]["data"]["zone"]
    return evidence({"sourceType":"OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN",
        "scope":"RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY",
        "sampleAsOfSlateDate":DATE,"sampleGameIds":ids,
        "sampleAppearanceCount":len(ids),
        "sampleSourcesByGame":{gid:[URL] for gid in ids},
        "sampleCoverageComplete":True,
        "sampleIncludesActualZeroShotAppearances":True,
        "unclassifiedOnNetShots":0,
        "zoneCounts":{zone:{"shotsOnGoal":sum(shots_by_game),
            "ownedGoals":sum(goal_counts),"gameIds":ids,"sourceUrls":[URL],
            "byGame":by_game}},
        "rinkBinsApproximateNotNhlEdgePolygons":True,
        "historicalOwnGoalCreditOnly":True,
        "notTonightGoalPrediction":True},source=URL)


def tied():
    a=skater(700,"High Slot",5,2)
    b=skater(701,"High Slot",5,2)
    return a,b


def test_recent_historical_goals_cannot_decide_equal_same_lane_shot_rates():
    a,b=tied()
    a["recentOrigin"]=recent(a,[2,0],[2,2])
    b["recentOrigin"]=recent(b,[0,0],[2,2])
    wins,rows=challenger_proof(a,[b],{"High Slot":{}},["High Slot"])
    assert wins is False
    assert rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"
    proof=rows[0]["independentRecentTieReview"]
    assert proof["result"]=="UNSEPARATED"
    assert proof["seasonOrRecentOwnedGoalTotalsNotUsed"] is True


def test_missing_or_same_recent_proof_never_manufactures_direct_recipient():
    a,b=tied()
    a["recentOrigin"]=recent(a,[2,0],[2,2])
    b.pop("recentOrigin")
    wins,rows=challenger_proof(a,[b],{"High Slot":{}},["High Slot"])
    assert wins is False and rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"
    assert rows[0]["independentRecentTieReview"] is None
    b["recentOrigin"]=recent(b,[2,0],[2,2])
    wins,rows=challenger_proof(a,[b],{"High Slot":{}},["High Slot"])
    assert wins is False and rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"


def test_exact_official_goal_not_assist_and_no_duplicate_on_net_origin():
    events=[{"gameId":"2026020134","eventId":"1","shooterId":"700",
        "type":"goal","x":60,"y":3,"date":"2026-11-10","sourceUrl":URL},
        {"gameId":"2026020134","eventId":"1","shooterId":"700",
        "type":"goal","x":60,"y":3,"date":"2026-11-10","sourceUrl":URL},
        {"gameId":"2026020134","eventId":"2","shooterId":"700",
        "type":"shot-on-goal","x":60,"y":3,"date":"2026-11-10","sourceUrl":URL},
        {"gameId":"2026020134","eventId":"3","shooterId":"700",
        "type":"missed-shot","x":60,"y":3,"date":"2026-11-10","sourceUrl":URL},
        {"gameId":"2026020134","eventId":"4","shooterId":"701",
        "type":"goal","x":60,"y":3,"date":"2026-11-10","sourceUrl":URL}]
    area=measured_recent_shooter_origins(events,"700")["High Slot"]
    assert area["shotsOnGoal"]==2
    assert area["ownedGoals"]==1
    assert area["sourceUrls"]==[URL]
    assert area["byGame"]==[{"gameId":"2026020134","date":"2026-11-10",
        "shotsOnGoal":2,"ownedGoals":1,"sourceUrls":[URL]}]
