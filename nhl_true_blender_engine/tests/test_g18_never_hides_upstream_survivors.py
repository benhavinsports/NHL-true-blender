"""G18 assembles the Core; it cannot retroactively erase a G0-G17 survivor.

Synthetic fixture only: no real scorer identity, goalie, or run is chosen.
"""
import json

from nhl_true_blender_engine.tests.test_engine import DATE, evidence, snapshot
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.engine import execute, MASTER


def test_unclassified_g18_label_does_not_disappear_a_full_g0_g17_game_survivor(tmp_path):
    con=open_db(str(tmp_path/"fixture.sqlite"))
    try:
        slate=snapshot(3)
        player=slate["games"][0]["rosters"]["T1A"]["data"]["players"][0]
        # G0-G17 remain identical to the ordinary source-qualified fixture.
        # This independently sourced G18 path assertion is contradictory:
        # it claims an unrelated player was displaced without any actual
        # G10.5 same-route rival. Nothing should force PRIMARY or TRANSFER.
        player["transferEvidence"]=evidence({
            "directRouteDisplaced":True, "routeZone":"slot",
            "displacedPlayerId":"not-a-same-lane-rival",
        })
        result=execute(con,slate,DATE,"CONFIRMED")
        pool=next(g for g in result["gameSurvivorPool"] if g["gameId"]=="5001")
        assert pool["status"]=="SURVIVOR"
        assert pool["survivor"]["playerId"]=="1010"
        assert pool["survivor"]["routeLabel"] is None
        assert pool["survivor"]["pathClassificationStatus"]=="G18_PATH_NOT_YET_CERTIFIED"
        assert result["uniqueGameSurvivors"]==3
        assert result["card"] is None
        assert any("G18 final source certification" in err for err in result["errors"])
        rows=con.execute(
            "SELECT gate,disposition FROM gates WHERE game_id=? AND player_id=?",
            ("5001","1010")).fetchall()
        by_gate={x["gate"]:x["disposition"] for x in rows}
        assert len([g for g in MASTER if g in by_gate])==20
        assert all(by_gate[g]=="PASS" for g in MASTER[:-1])
        assert by_gate["G18"]=="NOT_EXECUTED"
    finally:
        con.close()


def test_g18_without_path_still_never_forces_primary_transfer_or_who(tmp_path):
    con=open_db(str(tmp_path/"fixture2.sqlite"))
    try:
        slate=snapshot(3)
        player=slate["games"][0]["rosters"]["T1A"]["data"]["players"][0]
        player["transferEvidence"]=evidence({
            "directRouteDisplaced":True,"routeZone":"slot",
            "displacedPlayerId":"invented",
        })
        res=execute(con,slate,DATE,"PROJECTED")
        assert res["card"] is None
        source=next(g["survivor"] for g in res["gameSurvivorPool"] if g["gameId"]=="5001")
        path=source["pathClassificationEvidence"]
        assert path["path"] is None
        assert path["fallbackToPrimary"] is False
        assert path["pathQuotaApplied"] is False
        assert path["unknownIsNotAPath"] is True
        assert source["routeLabel"] is None
        assert all(g["status"]=="SURVIVOR" for g in res["gameSurvivorPool"])
    finally:
        con.close()
