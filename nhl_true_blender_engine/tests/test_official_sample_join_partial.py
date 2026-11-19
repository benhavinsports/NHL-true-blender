"""Independent boxscore/PBP joining never invents zeros or loses valid games."""
import asyncio

from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import attach, ingest
from nhl_true_blender_engine.official_boxscore_history import collect_sampled_boxes

DATE = "2026-11-19"
SRC = "https://api-web.nhle.com/v1/gamecenter/"

def snapshot():
    return {"games": [{"id": "900", "date": DATE, "away": "AAA", "home": "BBB",
        "goalies": {}, "coverage": {},
        "rosters": {
            "AAA": {"data": {"players": [{"id": "99", "name": "Test Skater"}]}},
            "BBB": {"data": {"players": []}}
        }}]}

class OfficialBoxClient:
    async def boxscore(self, game_id):
        return {"url": SRC + str(game_id) + "/boxscore",
            "data": {"playerByGameStats": {
                "homeTeam": {"forwards": [], "defense": []},
                "awayTeam": {"forwards": [
                    {"playerId": 99, "goals": 1, "shots": 3}], "defense": []}
            }}}

def goal(game_id, event_id):
    return {"gameId": str(game_id), "eventId": str(event_id),
            "shooterId": "99", "type": "goal",
            "date": "2026-11-10" if str(game_id)=="10" else "2026-11-11",
            "sourceUrl": SRC + str(game_id) + "/play-by-play"}

def find(con, kind):
    row=con.execute("SELECT payload FROM evidence WHERE kind=? ORDER BY observed_at DESC LIMIT 1",
                    (kind,)).fetchone()
    import json
    return json.loads(row["payload"]) if row else None

def test_pbp_fetch_failure_keeps_only_the_independently_verified_appearance(tmp_path):
    con=open_db(str(tmp_path/"case1.db"))
    dates={"10":"2026-11-10", "11":"2026-11-11"}
    stats=asyncio.run(collect_sampled_boxes(OfficialBoxClient(),con,snapshot(),DATE,
        "PROJECTED",dates,[goal(10,1)],pbp_verified_game_ids={"10"}))
    assert stats["pbpUnavailableGames"]==["11"]
    assert stats["reconciledSourceGames"]==1
    assert [a["gameId"] for a in find(con,"PLAYER_GAME_LOG")["appearances"]]==["10"]
    assert find(con,"PLAYER_OFFICIAL_GOALS")["goals"]==1
    assert len(find(con,"PLAYER_GOAL_EVENTS")["goals"])==1
    con.close()

def test_one_conflicted_goal_game_does_not_wipe_other_verified_game(tmp_path):
    con=open_db(str(tmp_path/"case2.db"))
    dates={"10":"2026-11-10", "11":"2026-11-11"}
    stats=asyncio.run(collect_sampled_boxes(OfficialBoxClient(),con,snapshot(),DATE,
        "PROJECTED",dates,[goal(10,1)],pbp_verified_game_ids={"10","11"}))
    assert len(stats["discrepancies"])==1
    assert stats["discrepancies"][0]["gameId"]=="11"
    assert find(con,"PLAYER_OFFICIAL_GOALS")["goals"]==1
    assert [a["gameId"] for a in find(con,"PLAYER_GAME_LOG")["appearances"]]==["10"]
    con.close()

def test_unreconciled_raw_pbp_does_not_overwrite_boxscore_goal_ids(tmp_path):
    con=open_db(str(tmp_path/"case3.db"))
    base={"slate_date":DATE,"stage":"PROJECTED","game_id":"900",
          "player_id":"99","source_url":SRC+"10/play-by-play"}
    ingest(con,{**base,"kind":"PLAYER_GOAL_EVENTS","evidence_id":"paired",
        "observed_at":"2026-11-19T15:00:00Z",
        "payload":{"scope":"SAMPLED_RECENT_TEAM_GAMES_ONLY",
                   "goals":[{"goalId":"10:1","date":"2026-11-10",
                             "sourceUrl":SRC+"10/play-by-play"}]}})
    ingest(con,{**base,"kind":"PLAYER_GOAL_EVENTS","evidence_id":"raw",
        "observed_at":"2026-11-19T15:00:01Z",
        "payload":{"scope":"SAMPLED_PRE_SLATE_GAMES_ONLY",
                   "goals":[{"goalId":"10:1","date":"2026-11-10",
                             "sourceUrl":SRC+"10/play-by-play"},
                            {"goalId":"11:1","date":"2026-11-11",
                             "sourceUrl":SRC+"11/play-by-play"}]}})
    s=snapshot()
    attach(con,s,DATE,"PROJECTED")
    reconciled=s["games"][0]["rosters"]["AAA"]["data"]["players"][0]["mappedGoals"]
    assert reconciled["data"]["scope"]=="SAMPLED_RECENT_TEAM_GAMES_ONLY"
    assert len(reconciled["data"]["goals"])==1
    assert len(reconciled["data"]["rawPbpSupplement"]["data"]["goals"])==2
    con.close()
