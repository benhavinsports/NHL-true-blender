"""G0 unresolved DOES NOT mean skipping G1-G18 or Phase-1 overlay.

Synthetic fixtures only. Research recipients are namespaced per actual goalie
branch and NEVER admitted to final Core selection without a real G0 decision.
"""
import json
from nhl_true_blender_engine.engine import (
    EXECUTION_ORDER, all_goalie_branches,execute)
from nhl_true_blender_engine.storage import open_db,get_card
from nhl_true_blender_engine.tests.test_engine import DATE,game,skater,evidence

def starter(pid,team):
    return evidence({
        "goalieId":pid,"team":team,"status":"EXPECTED",
        "weakZones":{"slot":{"savePct":0.8}},
        "sample":{"datedObservedShots":50},"counterevidence":{"reviewedAreas":["slot"]},
    })

def test_no_g0_winner_audits_both_teams_and_every_goalie_branch_without_picks(tmp_path):
    con=open_db(str(tmp_path/"actual_gates.sqlite"))
    g=game(1)
    g["goalies"][g["away"]]=[starter("away-1",g["away"])]
    g["goalies"][g["home"]]=[
        starter("home-1",g["home"]),starter("home-2",g["home"])]
    # Both sides have official skaters, not a fixture with an empty opponent.
    g["rosters"][g["home"]]=evidence({
        "players":[skater(9842,"slot",18,2)]})
    result=execute(con,{"games":[g]},DATE,"PROJECTED")
    assert result["card"] is None
    assert get_card(con,DATE) is None
    assert result["g0Directions"]==2
    assert result["eligibleSkaterRows"]==4
    # 3 away-team players against BOTH home goalie possibilities,
    # plus 1 home-team player against the away goalie: 7 original G0–G18 traces.
    assert result["unresolvedG0ResearchBranchCount"]==7
    assert result["unresolvedG0PlayerSourceChecks"]==7*len(EXECUTION_ORDER)
    assert result["gateRows"]==7*len(EXECUTION_ORDER)+2
    rows=con.execute("""SELECT player_id,gate,disposition,details
      FROM gates WHERE slate_date=? AND stage='PROJECTED'
       AND player_id LIKE 'G0_RESEARCH:%'""",(DATE,)).fetchall()
    assert len(rows)==7*len(EXECUTION_ORDER)
    for pid in {row["player_id"] for row in rows}:
        got=[row for row in rows if row["player_id"]==pid]
        assert len(got)==len(EXECUTION_ORDER)
        got.sort(key=lambda row:json.loads(row["details"])["executionIndex"])
        assert [row["gate"] for row in got]==EXECUTION_ORDER
        assert got[0]["disposition"]!="PASS"
        assert got[-1]["disposition"]!="PASS"
        assert all(json.loads(row["details"])["g0ResearchOnly"] is True
                   for row in got)
        assert all(json.loads(row["details"])["cannotBeSelectedOrPublished"] is True
                   for row in got)
    con.close()

def test_source_confirmed_starter_replaces_expected_in_both_phases():
    g=game(1)
    team=g["away"]
    projected=starter("projected-keeper",team)
    confirmed=starter("confirmed-keeper",team)
    confirmed["data"]["status"]="CONFIRMED"
    g["goalies"][team]=[projected,confirmed]
    for phase in ("PROJECTED","CONFIRMED"):
        branches=all_goalie_branches(g,phase)[team]
        assert len(branches)==1
        assert branches[0]["data"]["goalieId"]=="confirmed-keeper"
        assert branches[0]["data"]["status"]=="CONFIRMED"
