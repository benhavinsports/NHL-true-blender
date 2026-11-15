"""Regression: real NHL EDGE has rink shot origins, not anatomical net impact."""
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.edge_live import parse_edge,collect_edge,FAMILY

TODAY=datetime.now(ZoneInfo("America/New_York")).date().isoformat()

def wrapped(kind,pid):
    is_goalie=kind=="goalie"
    row={"area":"Crease"}
    if is_goalie:row.update(shotsAgainst=34,saves=30,goalsAgainst=4,savePctg=30/34,savePctgPercentile=.40)
    else:row.update(sog=16,goals=3,shootingPctg=3/16)
    return {"url":f"https://api-web.nhle.com/v1/edge/{kind}-shot-location-detail/{pid}/now",
            "observedAt":"2026-11-15T16:00:00Z",
            "data":{"player":{"id":int(pid)},"shotLocationDetails":[row],
                    "shotLocationTotals":[]}}

def test_official_nhl_edge_schema_exposes_scoped_real_statistics():
    goalie=parse_edge(wrapped("goalie",88),"goalie",88)
    player=parse_edge(wrapped("skater",99),"skater",99)
    assert goalie["rinkZoneRows"][0]["shotsAgainst"]==34
    assert player["rinkZoneRows"][0]["sog"]==16
    assert goalie["anatomicalGloveBlockerFiveHoleVerified"] is False
    assert player["scope"]==FAMILY
    assert all("fiveHole" not in v for v in (goalie,player))

def test_edge_rejects_player_id_or_unbalanced_save_denominator():
    with pytest.raises(ValueError,match="player ID mismatch"):
        parse_edge(wrapped("goalie",88),"goalie",123)
    payload=wrapped("goalie",88)
    payload["data"]["shotLocationDetails"][0]["saves"]=99
    with pytest.raises(ValueError,match="no source-consistent"):
        parse_edge(payload,"goalie",88)

@pytest.mark.asyncio
async def test_all_current_roster_players_and_goalies_are_collected_without_fabricating_g0(tmp_path):
    class Stub:
        calls=[]
        async def get(self,route):
            kind="goalie" if "/goalie-" in "/"+route else "skater"
            pid=route.split("/")[-2]
            self.calls.append((kind,pid))
            return wrapped(kind,pid)
    con=open_db(str(tmp_path/"edge.sqlite"))
    game={"id":"1001","away":"ANA","home":"CGY",
         "goalies":{},
         "rosters":{
             "ANA":{"data":{"goalies":[{"id":"88"}],
                     "players":[{"id":"99","position":"C"},{"id":"101","position":"D"}]}},
             "CGY":{"data":{"goalies":[{"id":"77"}],
                     "players":[{"id":"102","position":"L"}]}}
         }}
    stub=Stub()
    output=await collect_edge(stub,con,{"games":[game]},TODAY,"PROJECTED")
    assert output["goalieRinkProfiles"]==2
    assert output["skaterRinkProfiles"]==3
    assert output["allCurrentRosterIdentitiesChecked"]==5
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]==5
    assert game["goalies"]=={} # Collected context is NOT a starter/profile and cannot pass G0.
    assert output["anatomicalClaimCertified"] is False
    con.close()

@pytest.mark.asyncio
async def test_historical_runs_do_not_leak_current_season_goals_into_backtest(tmp_path):
    con=open_db(str(tmp_path/"history.sqlite"))
    output=await collect_edge(None,con,{"games":[]},"2026-10-01","PROJECTED")
    assert output["status"]=="NO_HISTORICAL_EDGE_SNAPSHOT_AS_OF"
    assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]==0
    con.close()
