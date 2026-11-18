"""Original Phase-1 functions execute inside the one G0-G18 gate sequence."""
import json
from datetime import datetime,timezone
from nhl_true_blender_engine.engine import (
    MASTER,OVERLAY,STEPS_BY_GATE,EXECUTION_ORDER,execute,
    verify_complete_matrix,gate_record)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,snapshot_without_shifts,DATE


def _rows(con,player_id):
    return con.execute("""SELECT gate,disposition,details FROM gates
        WHERE slate_date=? AND stage='CONFIRMED' AND player_id=?""",
        (DATE,player_id)).fetchall()


def test_original_functions_are_observed_inside_gates_before_g18(tmp_path):
    con=open_db(str(tmp_path/"unified.sqlite"))
    result=execute(con,snapshot_without_shifts(),DATE,"CONFIRMED")
    assert result["card"] is None
    for player_id in ("1010","1020","1030"):
        rows=_rows(con,player_id)
        assert len(rows)==len(MASTER)
        assert {x["gate"] for x in rows}==set(MASTER)
        assert not {x["gate"] for x in rows}.intersection(OVERLAY)
        functions=[]
        for row in rows:
            detail=json.loads(row["details"])
            observed=detail["evidence"].get("originalFunctionEvidence",[])
            assert [x["step"] for x in observed]==STEPS_BY_GATE[row["gate"]]
            functions.extend(observed)
        assert [f["step"] for f in functions] != [] 
        assert {f["step"] for f in functions}==set(OVERLAY)
        for fn in functions:
            proof=fn["evidence"]
            assert proof["independentOverlayEvaluation"] is True
            assert proof["checkedBeforeG18"] is True
            assert proof["masterGateVerdictCopied"] is False
        step7=next(f for f in functions if f["step"]=="Step7")
        assert step7["evidence"]["sourceTaggedBeforeFinalPick"] is True
        assert step7["sourceIds"]
        step8=next(f for f in functions if f["step"]=="Step8")
        assert step8["disposition"]=="NOT_EXECUTED"
        assert step8["evidence"]["nonblocking"] is True
        assert step8["evidence"]["actualShiftByShiftObserved"] is False
        assert step8["evidence"]["cannotInferShiftMatchupsFromShotOrigins"] is True
        step13=next(f for f in functions if f["step"]=="Step13")
        assert step13["evidence"]["qualitativeReviewActuallyPerformed"] is True
        assert step13["evidence"]["gematriaNumericFormulaRequired"] is False
    con.close()


def test_verifier_rejects_copied_source_function_inside_original_gate():
    s=snapshot(1);g=s["games"][0]
    rows=[gate_record(g,"GOALIE_DIRECTION:"+team,"G0","PASS",{})
          for team in (g["away"],g["home"])]
    for person in g["rosters"][g["away"]]["data"]["players"]:
        for gate in EXECUTION_ORDER:
            subchecks=[]
            for name in STEPS_BY_GATE[gate]:
                subchecks.append({"step":name,"disposition":"PASS",
                     "sourceIds":["https://www.nhl.com/"],
                     "evidence":{"independentOverlayEvaluation":True,
                                 "checkedBeforeG18":True,
                                 "masterGateVerdictCopied":name=="Step7"}})
            rows.append(gate_record(g,person["id"],gate,"PASS",
                         {"originalFunctionEvidence":subchecks}))
    direction={"attacker":g["away"],"defender":g["home"]}
    errors=verify_complete_matrix([g],rows,[],datetime.now(timezone.utc),
                                  {str(g["id"]):direction})
    assert any("lacks independent evidence" in e and "Step7" in e
               for e in errors)


def test_single_original_gate_order_retains_named_functions():
    assert EXECUTION_ORDER==MASTER
    assert len(MASTER)==20
    assert len(OVERLAY)==16
    assert EXECUTION_ORDER[-1]=="G18"
