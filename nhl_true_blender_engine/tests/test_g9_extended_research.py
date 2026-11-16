"""A wider defensive source search must never inflate player appearance logs."""
import pytest
from nhl_true_blender_engine import historical_shots as h
from nhl_true_blender_engine.secondary_sources import TEAM_SLUGS
from nhl_true_blender_engine.storage import open_db

@pytest.mark.asyncio
async def test_g9_league_history_is_extended_without_extending_eight_game_player_logs(
    tmp_path, monkeypatch
):
    team_numbers={k:i+10 for i,k in enumerate(sorted(TEAM_SLUGS))}
    queried=[]
    class Client:
        async def get(self,route):
            team=route.split("/")[1]
            games=[{
                "id":str(team_numbers[team]*1000+i),
                "gameDate":f"2026-10-{i+1:02d}",
                "gameState":"OFF",
                "homeTeam":{"id":team_numbers[team],"abbrev":team},
                "awayTeam":{"id":9999,"abbrev":"OPP"},
            } for i in range(20)]
            return {"data":{"games":games},"url":"https://api-web.nhle.com/v1/"+route}
        async def play_by_play(self,game_id):
            return {"data":{"plays":[]},"url":f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"}
    async def boxes(client,con,snapshot,date,stage,target_ids,target_events):
        queried.append(set(target_ids))
        return {"status":"EMPTY_FIXTURE"}
    async def shifts(*args):
        return {"byDefendingTeamId":{},"historicalOnly":True}
    monkeypatch.setattr(h,"collect_sampled_boxes",boxes)
    monkeypatch.setattr(h,"collect_shift_coverage",shifts)
    roster={"data":{"players":[]}}
    snapshot={"games":[{"id":"54321","away":"MTL","home":"NYR",
                       "rosters":{"MTL":roster,"NYR":roster}}]}
    con=open_db(str(tmp_path/"source.sqlite"))
    try:
        result=await h.collect_history(Client(),con,snapshot,"2026-11-16","PROJECTED")
        assert result["playerRecentHistoryWindowUnchanged"]==8
        assert result["G9IndependentPeerHistoryWindow"]==16
        assert result["coveragePeerGames"]==len(team_numbers)*16
        assert result["historicalGames"]==16
        assert len(queried)==1 and len(queried[0])==16
        assert result["coveragePeerGames"]>result["historicalGames"]
    finally:
        con.close()
