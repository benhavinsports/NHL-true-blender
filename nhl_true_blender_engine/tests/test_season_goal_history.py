"""Independent official full-season goal evidence; synthetic test inputs only."""
import json
from nhl_true_blender_engine.season_goal_history import decode_dated_goals
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE,evidence
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.storage import open_db

def test_dated_official_season_goals_exclude_same_day_and_future():
    data={"gameLog":[
        {"gameId":2026020001,"gameDate":"2026-11-02","goals":2,"shots":5},
        {"gameId":2026020002,"gameDate":"2026-11-10","goals":0,"shots":2},
        {"gameId":2026020003,"gameDate":"2026-11-16","goals":3,"shots":5},
        {"gameId":2026020004,"gameDate":"2026-11-20","goals":1,"shots":3},
    ]}
    parsed=decode_dated_goals(data,8470000,"2026-11-16")
    assert parsed["officialPastSeasonGoals"]==2
    assert len(parsed["datedGames"])==2
    assert parsed["goalScoringGames"]==[{
        "gameId":"2026020001","date":"2026-11-02","goals":2,"shotsOnGoal":5}]
    assert parsed["sameSlateDateExcluded"] is True
    assert parsed["noSyntheticGoalEventIds"] is True

def test_malformed_goal_log_never_becomes_positive_certification():
    assert decode_dated_goals({},123,"2026-11-16") is None
    assert decode_dated_goals({"gameLog":[{
        "gameId":"1","gameDate":"2026-11-03","goals":2,"shots":1}]},123,"2026-11-16") is None
    assert decode_dated_goals({"gameLog":[{
        "gameId":"1","gameDate":"2026-11-03","goals":1,"shots":1},
        {"gameId":"1","gameDate":"2026-11-04","goals":1,"shots":1}]},123,"2026-11-16") is None

def test_full_engine_accepts_official_earlier_season_goal_not_in_last_eight(tmp_path):
    s=snapshot()
    g=s["games"][0]
    p=g["rosters"][g["away"]]["data"]["players"][0]
    # This scorer's recorded shot origins show 3 OWN goals, but none
    # occurred in the latest eight games. Neither sample is invented.
    p["mappedGoals"]=evidence({"goals":[]})
    p["officialGoalTotal"]=evidence({"goals":0})
    p["gameLog"]=evidence({"appearances":[
        {"date":"2026-11-08","shots":2},
        {"date":"2026-11-10","shots":1}]})
    p["seasonHistory"]=evidence({
        "playerId":str(p["id"]),
        "sourceType":"NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG",
        "scope":"OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE",
        "officialPastSeasonGoals":4,
        "goalScoringGames":[{"gameId":"2026020100","date":"2026-10-18",
                             "goals":4,"shotsOnGoal":7}],
        "sameSlateDateExcluded":True,"noSyntheticGoalEventIds":True},
        "https://api-web.nhle.com/v1/player/1010/game-log/20262027/2")
    con=open_db(str(tmp_path/"season-route.sqlite"))
    try:
        result=execute(con,s,DATE,"CONFIRMED")
        assert result["card"] is not None,result["errors"]
        rows=con.execute("""SELECT gate,disposition,details FROM gates
             WHERE game_id=? AND player_id=? AND gate IN ('G10','G15')""",
             (str(g["id"]),str(p["id"]))).fetchall()
        assert {r["gate"]:r["disposition"] for r in rows}=={"G10":"PASS","G15":"PASS"}
        g10=json.loads(next(r["details"] for r in rows if r["gate"]=="G10"))
        assert g10["evidence"]["historicalDirectGoalRecipientVerificationMethod"]=="FULL_SEASON_GAME_LOG"
        assert g10["evidence"]["futureNotAssistOrFeederProven"] is False
        g15=json.loads(next(r["details"] for r in rows if r["gate"]=="G15"))
        assert g15["evidence"]["seasonAndReleaseGoalCreditsConsistent"] is True
    finally:
        con.close()

def test_unverified_or_inconsistent_season_goal_cannot_pass(tmp_path):
    s=snapshot()
    g=s["games"][0]
    p=g["rosters"][g["away"]]["data"]["players"][0]
    p["mappedGoals"]=evidence({"goals":[]})
    p["officialGoalTotal"]=evidence({"goals":0})
    p["seasonHistory"]=evidence({
        "playerId":str(p["id"]), "officialPastSeasonGoals":1,
        "sourceType":"NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG",
        "scope":"OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE",
        "goalScoringGames":[{"gameId":"2026020100","date":"2026-10-18","goals":1}]},
        "https://api-web.nhle.com/v1/player/1010/game-log/20262027/2")
    con=open_db(str(tmp_path/"season-contradiction.sqlite"))
    try:
        result=execute(con,s,DATE,"CONFIRMED")
        assert result["card"] is None
        row=con.execute("""SELECT disposition,details FROM gates WHERE
              game_id=? AND player_id=? AND gate='G15'""",
              (str(g["id"]),str(p["id"]))).fetchone()
        assert row["disposition"]=="NOT_EXECUTED"
    finally:
        con.close()
