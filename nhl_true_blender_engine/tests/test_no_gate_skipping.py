"""Full G0–G18 source checks must not stop when an earlier gate eliminates a skater."""
import json
from nhl_true_blender_engine.engine import execute,MASTER,OVERLAY,EXECUTION_ORDER
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE

def test_eliminated_depth_player_still_receives_real_subsequent_checks(tmp_path):
    con=open_db(str(tmp_path/"no_skips.sqlite"))
    result=execute(con,snapshot(),DATE,"CONFIRMED")
    assert result["card"],result["errors"]
    # Test fixture player 1012 is explicitly OUT and independently weaker
    # from a nonmatching area, yet every master and overlay check executes
    # in the single authoritative order.
    rows=con.execute("""SELECT gate,disposition,details FROM gates WHERE
        slate_date=? AND stage='CONFIRMED' AND game_id='5001' AND player_id='1012'""",
        (DATE,)).fetchall()
    by_gate={x["gate"]:x for x in rows}
    assert all(g in by_gate for g in MASTER+OVERLAY)
    ordered=sorted(rows,key=lambda row:json.loads(row["details"])["executionIndex"])
    assert [row["gate"] for row in ordered]==EXECUTION_ORDER
    assert ordered[-1]["gate"]=="G18"
    assert by_gate["G2"]["disposition"]=="ELIMINATED"
    assert not any(x["disposition"]=="SKIPPED_AFTER_ELIMINATION" for x in rows)
    assert by_gate["G18"]["disposition"]=="NOT_EXECUTED"
    later=json.loads(by_gate["G13"]["details"])["evidence"]
    assert later["alreadyEliminatedAtGate"]=="G2"
    assert later["laterPositiveEvidenceCannotReinstate"] is True
    assert "1012" not in [p["playerId"] for p in result["card"]["current_legs"]]
    census=certify_gates(con,DATE,"CONFIRMED",3)
    assert all(x.get("SKIPPED_AFTER_ELIMINATION",0)==0
               for x in census["masterGateDispositions"].values())
    con.close()
