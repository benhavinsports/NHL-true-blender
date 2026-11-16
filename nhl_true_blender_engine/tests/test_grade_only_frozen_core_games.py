"""Official grading waits for exactly the locked Core's game finals, not
unrelated late NHL games. No fixtures represent live real November outcomes.
"""
import asyncio
import pytest
from nhl_true_blender_engine import storage
from nhl_true_blender_engine.sources import official_final_grade

DATE="2026-11-15"
IDS=("2026020326","2026020327","2026020328")
PLAYERS=("8480803","8480027","8480028")

def score(gid,state):
    return {"id":gid,"awayTeam":{"abbrev":"AWY"},
            "homeTeam":{"abbrev":"HME"},
            "startTimeUTC":"2026-11-16T01:00:00Z",
            "gameState":state}

class OfficialNHLFixture:
    def __init__(self, core_states=("FINAL","OFF","FINAL")):
        self.games=[score(gid,st) for gid,st in zip(IDS,core_states)]
        self.games.extend([score("unrelated-late-01","LIVE"),
                           score("unrelated-late-02","FUT")])
        self.game_requests=[]

    async def score(self,date):
        assert date==DATE
        return {"data":{"games":self.games},
                "url":"https://api-web.nhle.com/v1/score/"+DATE,
                "observedAt":"2026-11-16T04:30:00Z"}

    async def play_by_play(self,gid):
        self.game_requests.append(("pbp",gid))
        i=IDS.index(gid)
        return {"data":{"plays":[{"typeDescKey":"goal","eventId":i+1,
                    "periodDescriptor":{"periodType":"REG"},
                    "details":{"scoringPlayerId":int(PLAYERS[i])}}] if i==1 else []},
                "url":f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play"}

    async def boxscore(self,gid):
        self.game_requests.append(("box",gid))
        i=IDS.index(gid)
        return {"data":{"playerByGameStats":{
                "homeTeam":{"forwards":[{"playerId":int(PLAYERS[i]),
                                           "goals":1 if i==1 else 0}],
                            "defense": []},
                "awayTeam":{"forwards":[],"defense":[]}}},
                "url":f"https://api-web.nhle.com/v1/gamecenter/{gid}/boxscore"}

def setup(monkeypatch):
    card={"card_id":"frozen-original",
          "current_legs":[{"gameId":gid,"playerId":pid}
                          for gid,pid in zip(IDS,PLAYERS)]}
    monkeypatch.setattr(storage,"get_card",lambda con,date:card)
    result={}
    def grade(con,date,goals,sources,all_final):
        assert date==DATE
        assert all_final is True
        assert len(goals)==3
        assert len(sources)==7
        result.update(goals=goals,sources=sources)
        return {"result":"LOSS","legs":[]}
    monkeypatch.setattr(storage,"grade_frozen_card",grade)
    return result

def test_noncore_live_games_do_not_delay_original_core_grading(monkeypatch):
    recorded=setup(monkeypatch)
    client=OfficialNHLFixture()
    report=asyncio.run(official_final_grade(client,object(),DATE))
    assert report["status"]=="GRADED_OFFICIAL_GOAL_EVENTS"
    assert recorded["goals"]=={(IDS[0],PLAYERS[0]):0,
                               (IDS[1],PLAYERS[1]):1,
                               (IDS[2],PLAYERS[2]):0}
    assert len(client.game_requests)==6
    assert all(gid in IDS for method,gid in client.game_requests)

def test_one_nonfinal_frozen_game_blocks_entire_official_grade(monkeypatch):
    setup(monkeypatch)
    client=OfficialNHLFixture(("FINAL","LIVE","OFF"))
    report=asyncio.run(official_final_grade(client,object(),DATE))
    assert report["grade"] is None
    assert report["status"]=="CORE_MATCHUPS_NOT_ALL_OFFICIALLY_FINAL"
    assert report["pendingCoreGameIds"]==[IDS[1]]
    assert report["officiallyFinalCoreGames"]==2
    assert client.game_requests==[]

def test_missing_original_game_in_official_schedule_fails_closed(monkeypatch):
    setup(monkeypatch)
    client=OfficialNHLFixture()
    client.games=[g for g in client.games if str(g["id"])!=IDS[0]]
    with pytest.raises(Exception,match="Original frozen Core game"):
        asyncio.run(official_final_grade(client,object(),DATE))
    assert client.game_requests==[]
