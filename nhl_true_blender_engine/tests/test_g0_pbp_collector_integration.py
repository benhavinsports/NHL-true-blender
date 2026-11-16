"""Integration of missing NHL EDGE starter -> official goalie game log -> PBP -> G0.

All NHL-API-shaped receipts below are SYNTHETIC for deterministic tests.
"""
import asyncio
from nhl_true_blender_engine.goalie_history_fallback import collect_goalie_pbp_fallback,SOURCE
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.engine import g0_full_slate
from nhl_true_blender_engine.storage import open_db

DATE="2026-11-16"
RAW="https://api-web.nhle.com/v1/"
GOALIE="44"
TEAMS=("AAA","BBB")

class FakeOfficialNHL:
    def __init__(self):
        self.game_requests=[]
        self.log_requests=[]
    async def game_log(self,pid,season):
        self.log_requests.append((str(pid),season))
        if season=="20262027":
            games=[{"gameId":200+i,"gameDate":f"2026-11-{9-i:02d}"}
                   for i in range(5)]
        else:
            games=[]
        return {"url":RAW+f"player/{pid}/game-log/{season}/2",
                "data":{"gameLog":games},"observedAt":"2026-11-16T05:15:00Z"}
    async def play_by_play(self,gid):
        self.game_requests.append(str(gid))
        opponent=45+int(gid)-200
        plays=[]
        for goalie_id,conceded in [(44,8),(opponent,1+int(gid)-200)]:
            for i in range(25):
                details={"goalieInNetId":int(goalie_id),
                     "xCoord":82,"yCoord":4,
                     "scoringPlayerId":998,"shootingPlayerId":998}
                plays.append({"typeDescKey":"goal" if i<conceded else "shot-on-goal",
                     "eventId":(goalie_id*1000)+i+1,
                     "periodDescriptor":{"periodType":"REG"},
                     "details":details})
        return {"url":RAW+f"gamecenter/{gid}/play-by-play",
                "observedAt":"2026-11-16T05:20:00Z","data":{"plays":plays}}

def test_live_collector_shape_reconstructs_missing_goalie_and_attaches_source(tmp_path):
    db=open_db(str(tmp_path/"historical-goalie.sqlite"))
    g={"id":"9999","date":DATE,"away":TEAMS[0],"home":TEAMS[1],
       "goalies":{TEAMS[0]:[],TEAMS[1]:[{
           "sourceUrl":"https://www.betweenthelineshockey.com/tonight.md",
           "observedAt":"2026-11-16T05:10:00Z",
           "data":{"goalieId":"44","team":TEAMS[1],"status":"EXPECTED"}}]},
       "rosters":{}, "coverage":{}}
    slate={"games":[g]};client=FakeOfficialNHL()
    result=asyncio.run(collect_goalie_pbp_fallback(client,db,slate,DATE,"PROJECTED"))
    assert result["sourceType"]==SOURCE
    assert result["historicalNhlGamesFetched"]==5
    assert result["goaliesNeedingPbpResearch"]==1
    assert result["fallbackProfiles"]==1
    assert result["goaliesWithPeerComparedOrigins"]==1
    assert result["sourceFailures"]==[]
    assert len(client.game_requests)==5
    assert len(client.log_requests)==2
    record=db.execute("""SELECT payload,source_url FROM evidence
          WHERE stage='PROJECTED' AND game_id='9999' AND kind='GOALIE_PROFILE'""").fetchone()
    assert record is not None
    assert "/gamecenter/" in record["source_url"]
    attach(db,slate,DATE,"PROJECTED")
    goalie=g["goalies"][TEAMS[1]][0]
    assert goalie["data"]["status"]=="EXPECTED"
    assert goalie["data"]["sourceClass"]=="INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY"
    assert goalie["data"]["fullySourceComparedAreas"]==1
    assert goalie["data"]["weakZones"]["Low Slot"]["goalsAgainst"]==40
    assert goalie["data"]["anatomicalWeaknessCertified"] is False
    directions,errors=g0_full_slate([g],"PROJECTED")
    assert directions[0]["goalieProfileEvidenced"] is True
    assert directions[1]["goalieProfileEvidenced"] is False
    db.close()

def test_no_goalie_history_does_not_manufacture_scoring_vulnerability(tmp_path):
    db=open_db(str(tmp_path/"no-data.sqlite"))
    g={"id":"9999","date":DATE,"away":TEAMS[0],"home":TEAMS[1],
       "goalies":{TEAMS[0]:[],TEAMS[1]:[{
           "sourceUrl":"https://www.betweenthelineshockey.com/tonight.md",
           "observedAt":"2026-11-16T05:10:00Z",
           "data":{"goalieId":"44","team":TEAMS[1],"status":"EXPECTED"}}]},
       "rosters":{}, "coverage":{}}
    client=FakeOfficialNHL()
    async def none(pid,season):
        return {"data":{"gameLog":[]}}
    client.game_log=none
    result=asyncio.run(collect_goalie_pbp_fallback(client,db,{"games":[g]},DATE,"PROJECTED"))
    assert result["fallbackProfiles"]==0
    assert result["goaliesWithPeerComparedOrigins"]==0
    assert g0_full_slate([g],"PROJECTED")[0][0]["goalieProfileEvidenced"] is False
    db.close()


def test_club_schedule_backfills_when_goalie_personal_game_log_is_missing(tmp_path):
    db=open_db(str(tmp_path/"club-history.sqlite"))
    g={"id":"9999","date":DATE,"away":TEAMS[0],"home":TEAMS[1],
       "goalies":{TEAMS[0]:[],TEAMS[1]:[{
           "sourceUrl":"https://www.betweenthelineshockey.com/tonight.md",
           "observedAt":"2026-11-16T05:10:00Z",
           "data":{"goalieId":"44","team":TEAMS[1],"status":"EXPECTED"}}]},
       "rosters":{}, "coverage":{}}
    client=FakeOfficialNHL()
    async def empty_log(pid,season):
        return {"data":{"gameLog":[]}}
    client.game_log=empty_log
    async def actual_club_schedule(route):
        assert route.startswith("club-schedule-season/BBB/")
        if route.endswith("/20262027"):
            games=[{"id":200+i,"gameDate":f"2026-11-{9-i:02d}",
                    "gameState":"OFF"} for i in range(5)]
            games.append({"id":999,"gameDate":DATE,"gameState":"OFF"})
        else:
            games=[]
        return {"data":{"games":games}}
    client.get=actual_club_schedule
    result=asyncio.run(collect_goalie_pbp_fallback(
        client,db,{"games":[g]},DATE,"PROJECTED"))
    assert result["goaliesWithOfficialPersonalHistory"]==0
    assert result["clubScheduleGamesRecovered"]==5
    assert result["fallbackProfiles"]==1
    assert result["goaliesWithPeerComparedOrigins"]==1
    assert result["historicalOnly"] is True
    assert "999" not in client.game_requests
    db.close()
