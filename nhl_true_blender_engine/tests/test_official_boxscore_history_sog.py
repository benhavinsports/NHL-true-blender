import asyncio
import json

from nhl_true_blender_engine.official_boxscore_history import collect_sampled_boxes
from nhl_true_blender_engine.historical_shots import reconcile_player_sog_by_game
from nhl_true_blender_engine.storage import open_db

GAME="2026020001"
DATE="2026-11-01"
BOX="https://api-web.nhle.com/v1/gamecenter/2026020001/boxscore"
PBP="https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play"


class FakeClient:
    async def boxscore(self,game_id):
        assert str(game_id)==GAME
        return {"url":BOX,"data":{"playerByGameStats":{
            "homeTeam":{"forwards":[{"playerId":700,"goals":1,"sog":2,"shots":1}],"defense":[]},
            "awayTeam":{"forwards":[],"defense":[]},
        }}}


def test_nhl_boxscore_sog_field_is_preferred_over_legacy_shots(tmp_path):
    snapshot={"games":[{
        "id":"TODAY","date":"2026-11-16","away":"BOS","home":"NYR",
        "rosters":{
            "BOS":{"data":{"players":[{"id":700,"name":"Shooter"}]}},
            "NYR":{"data":{"players":[]}},
        },
    }]}
    events=[{"gameId":GAME,"eventId":"1","shooterId":"700","type":"goal",
             "date":DATE,"sourceUrl":PBP}]
    con=open_db(str(tmp_path/"boxscore-sog.sqlite"))
    try:
        asyncio.run(collect_sampled_boxes(
            FakeClient(),con,snapshot,"2026-11-16","PROJECTED",
            {GAME:DATE},events,pbp_verified_game_ids={GAME}))
        row=con.execute(
            "SELECT payload FROM evidence WHERE kind='PLAYER_PRESSURE' AND player_id='700'"
        ).fetchone()
        assert row is not None
        payload=json.loads(row["payload"])
        assert payload["recentAppearanceShots"]==[2]
        assert payload["appearances"][0]["shotsOnGoal"]==2
    finally:
        con.close()


def test_player_recent_sog_reconciliation_rejects_missing_or_mismatched_pbp():
    appearances=[
        {"gameId":"g1","date":"2026-11-01","shotsOnGoal":2},
        {"gameId":"g2","date":"2026-11-02","shotsOnGoal":0},
    ]
    matching=[
        {"gameId":"g1","shooterId":"700","type":"goal"},
        {"gameId":"g1","shooterId":"700","type":"shot-on-goal"},
    ]
    good=reconcile_player_sog_by_game(appearances,matching,"700")
    assert good["pbpBoxscoreSogReconciled"] is True
    assert good["pbpOnNetShotsByGame"]=={"g1":2,"g2":0}
    assert good["boxscoreShotsOnGoalByGame"]=={"g1":2,"g2":0}
    bad=reconcile_player_sog_by_game(appearances,matching[:1],"700")
    assert bad["pbpBoxscoreSogReconciled"] is False
    assert bad["pbpBoxscoreSogMismatches"]==[
        {"gameId":"g1","boxscoreShotsOnGoal":2,"pbpShooterOnNetEvents":1}]
