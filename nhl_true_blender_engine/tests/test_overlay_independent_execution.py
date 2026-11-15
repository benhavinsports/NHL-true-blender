"""An overlay receipt is not the same as running its original Phase-1 rule."""
import json
from nhl_true_blender_engine.engine import (MASTER,OVERLAY,execute,
     verify_complete_matrix,gate_record)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE

def _rows(con,player_id):
    return con.execute("""SELECT gate,disposition,details FROM gates
        WHERE slate_date=? AND stage='CONFIRMED' AND player_id=?""",
        (DATE,player_id)).fetchall()

def test_16_individual_overlay_source_checks_occur_before_G18(tmp_path):
    con=open_db(str(tmp_path/"overlay.sqlite"))
    result=execute(con,snapshot(),"{}".format(DATE),"CONFIRMED")
    assert result["card"] is not None,result["errors"]
    for player_id in ("1010","1020","1030"):
        rows=_rows(con,player_id)
        overlays=[x for x in rows if x["gate"] in OVERLAY]
        assert len(overlays)==16
        assert {x["gate"] for x in overlays}==set(OVERLAY)
        for row in overlays:
            detail=json.loads(row["details"])
            proof=detail["evidence"]
            assert proof["independentOverlayEvaluation"] is True
            assert proof["checkedBeforeG18"] is True
            assert proof["masterGateVerdictCopied"] is False
        step7=json.loads(next(r["details"] for r in overlays if r["gate"]=="Step7"))
        assert step7["evidence"]["sourceTaggedBeforeFinalPick"] is True
        assert step7["sourceIds"]
        step8=next(x for x in overlays if x["gate"]=="Step8")
        # Fixture includes game-level defensive weakness, but does not invent
        # shift-by-shift events. The independent overlay must flag this gap.
        assert step8["disposition"]=="NOT_EXECUTED"
        details=json.loads(step8["details"])["evidence"]
        assert details["actualShiftByShiftObserved"] is False
        assert details["cannotInferShiftMatchupsFromShotOrigins"] is True
        step13=json.loads(next(r["details"] for r in overlays if r["gate"]=="Step13"))
        assert step13["evidence"]["qualitativeReviewActuallyPerformed"] is True
        assert step13["evidence"]["gematriaNumericFormulaRequired"] is False
    con.close()

def test_verifier_rejects_old_aliased_overlay_rows_even_when_counts_match():
    from datetime import datetime,timezone
    s=snapshot(1);g=s["games"][0];p=g["rosters"][g["away"]]["data"]["players"][0]
    rows=[gate_record(g,p["id"],gate,"PASS",{"archetype":"fixture"})
          for gate in MASTER+OVERLAY]
    rows += [gate_record(g,"GOALIE_DIRECTION:"+team,"G0","PASS",{})
             for team in (g["away"],g["home"])]
    direction={"attacker":g["away"],"defender":g["home"]}
    errors=verify_complete_matrix([g],rows,[],datetime.now(timezone.utc),
                                  {str(g["id"]):direction})
    assert any("copied verdict" in e and "Step7" in e for e in errors)

def test_original_master_and_overlay_order_stays_exact():
    assert MASTER == ([f"G{i}" for i in range(11)]+["G10.5"]+
                       [f"G{i}" for i in range(11,19)])
    assert OVERLAY == ([f"Step{i}" for i in range(11)]+["Step10.5"]+
                        [f"Step{i}" for i in range(11,15)])
