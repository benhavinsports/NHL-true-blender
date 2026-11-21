"""Puck-drop freeze is enforced at roster collection, source research and G0."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch

import pytest

from nhl_true_blender_engine import engine, sources
from nhl_true_blender_engine.source_recovery import pregame_only_snapshot


def test_pregame_snapshot_keeps_only_games_before_their_own_puck_drop():
    now=datetime(2026,11,21,22,0,tzinfo=timezone.utc)
    snapshot={"games":[
        {"id":"live","gameState":"LIVE","startUTC":"2026-11-21T18:00:00Z"},
        {"id":"future","gameState":"FUT","startUTC":"2026-11-21T23:00:00Z"},
    ]}
    assert [g["id"] for g in pregame_only_snapshot(snapshot,now)["games"]]==["future"]


def test_g0_does_not_reaudit_a_game_after_puck_drop():
    now=datetime(2026,11,21,22,0,tzinfo=timezone.utc)
    started={"id":"1","away":"EDM","home":"CAR","gameState":"LIVE",
             "startUTC":"2026-11-21T18:00:00Z"}
    with patch.object(engine,"all_goalie_branches",
                      side_effect=AssertionError("started game must be frozen")):
        assert engine.g0_full_slate([started],"PROJECTED",now=now)==([],[])


def test_historical_replay_cutoff_keeps_its_pregame_g0_review():
    cutoff=datetime(2026,11,21,17,0,tzinfo=timezone.utc)
    future={"id":"1","away":"EDM","home":"CAR","gameState":"FUT",
            "startUTC":"2026-11-21T18:00:00Z"}
    with patch.object(engine,"all_goalie_branches",
                      return_value={"EDM":[],"CAR":[]}):
        scan,errors=engine.g0_full_slate([future],"PROJECTED",now=cutoff)
    assert len(scan)==2
    assert len(errors)==2


@pytest.mark.asyncio
async def test_official_slate_does_not_fetch_rosters_for_started_games():
    now=datetime.now(timezone.utc)
    et_date=now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    started=(now-timedelta(minutes=5)).isoformat()
    future=(now+timedelta(hours=1)).isoformat()
    calls=[]
    class Client:
        async def score(self,date):
            return {"url":"https://api-web.nhle.com/v1/score/"+date,
                    "observedAt":now.isoformat(),
                    "data":{"games":[
                        {"id":"1","awayTeam":{"abbrev":"EDM"},
                         "homeTeam":{"abbrev":"CAR"},"startTimeUTC":started,
                         "gameState":"LIVE"},
                        {"id":"2","awayTeam":{"abbrev":"BUF"},
                         "homeTeam":{"abbrev":"FLA"},"startTimeUTC":future,
                         "gameState":"FUT"},
                    ]}}
        async def roster(self,team):
            calls.append(team)
            return {"url":"https://api-web.nhle.com/v1/roster/"+team,
                    "observedAt":now.isoformat(),
                    "data":{"forwards":[],"defensemen":[],"goalies":[]}}
    result=await sources.official_slate(Client(),et_date)
    assert calls==["BUF","FLA"]
    assert result["games"][0]["rosters"]=={}
    assert set(result["games"][1]["rosters"])=={"BUF","FLA"}
