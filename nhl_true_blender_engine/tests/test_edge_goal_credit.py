"""G10 does not confuse a scoreless eight-game sample with a scoreless season."""
from nhl_true_blender_engine.storage import open_db,record_evidence
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.edge_derived_routes import derive_nhl_edge_attacks

DATE="2026-11-15"
SRC="https://api-web.nhle.com/v1/"
def write(con,id,kind,payload,when="2026-11-15T14:00:00Z"):
    record_evidence(con,{"evidence_id":id,"slate_date":DATE,"stage":"PROJECTED",
        "game_id":"1234","player_id":"99","kind":kind,
        "source_url":SRC+"edge/skater-shot-location-detail/99/now",
        "observed_at":when,"payload":payload})

def game():
    return {"id":"1234","away":"BOS","home":"ANA","goalies":{},
        "coverage":{},"rosters":{
            "BOS":{"data":{"players":[{"id":"99","name":"Route Skater","position":"C"}]}},
            "ANA":{"data":{"players":[]}}}}

def test_own_edge_season_goals_prove_credited_recipient_despite_recent_scoreless_sample(tmp_path):
    con=open_db(str(tmp_path/"db.sqlite"))
    g=game()
    write(con,"recent","PLAYER_FINISH_CREDIT",
          {"recipient":None,"creditedGoalsVerified":True,
           "ownedGoalsInActualAppearances":0,"scope":"SAMPLED_RECENT_TEAM_GAMES_ONLY"},
          "2026-11-15T11:00:00Z")
    write(con,"shotareas","NHL_EDGE_SKATER_RINK_ORIGIN",
          {"scope":"NHL_EDGE_SHOT_ORIGIN_RINK_ONLY",
           "rinkZoneRows":[{"area":"Low Slot","sog":24,"goals":3},
                           {"area":"L Circle","sog":6,"goals":1}]})
    report=derive_nhl_edge_attacks(con,{"games":[g]},DATE,"PROJECTED")
    assert report["sourceBackedSkaterOwnGoalCredits"]==1
    attach(con,{"games":[g]},DATE,"PROJECTED")
    credit=g["rosters"]["BOS"]["data"]["players"][0]["finishOwnership"]["data"]
    assert credit["recipient"] is True
    assert credit["creditedGoalsVerified"] is True
    assert credit["ownedSeasonGoalsFromNhlEdgeShotOrigins"]==4
    assert credit["recentGameLogSupplement"]["data"]["recipient"] is None
    assert credit["notClaimOfTonightGoalCredit"] is True
    con.close()

def test_does_not_invent_goal_ownership_when_edge_has_zero_credited_goals(tmp_path):
    con=open_db(str(tmp_path/"db.sqlite"))
    g=game()
    write(con,"recent","PLAYER_FINISH_CREDIT",
          {"recipient":None,"creditedGoalsVerified":True,
           "ownedGoalsInActualAppearances":0,"scope":"SAMPLED_RECENT_TEAM_GAMES_ONLY"})
    write(con,"shotareas","NHL_EDGE_SKATER_RINK_ORIGIN",
          {"scope":"NHL_EDGE_SHOT_ORIGIN_RINK_ONLY",
           "rinkZoneRows":[{"area":"Low Slot","sog":12,"goals":0}]})
    report=derive_nhl_edge_attacks(con,{"games":[g]},DATE,"PROJECTED")
    assert report["sourceBackedSkaterOwnGoalCredits"]==0
    attach(con,{"games":[g]},DATE,"PROJECTED")
    credit=g["rosters"]["BOS"]["data"]["players"][0]["finishOwnership"]["data"]
    assert credit["recipient"] is None
    con.close()
