"""One original G0-G18 pipeline: Step-named functions are embedded, not duplicate gates."""
import json

from nhl_true_blender_engine.engine import execute, OVERLAY
from nhl_true_blender_engine.gate_input_diagnostics import explain_live_blockers
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot, DATE


def test_original_step_functions_read_from_their_owning_gates(tmp_path):
    con=open_db(str(tmp_path / "embedded-diagnostics.sqlite"))
    try:
        result=execute(con,snapshot(2),DATE,"CONFIRMED")
        assert result["card"] is not None, result["errors"]
        diag=explain_live_blockers(con,DATE,"CONFIRMED")
        matrix=diag["candidateGateMatrix"]
        assert matrix
        assert diag["allCandidatesHaveEveryMasterAndOverlayRecord"] is True
        for candidate in matrix:
            assert candidate["missingMasterRecords"]==[]
            assert candidate["missingOverlayRecords"]==[]
            assert set(candidate["overlayDispositions"])==set(OVERLAY)
            assert candidate["overlayGateCount"]==len(OVERLAY)
        selected={str(x["playerId"]) for x in result["card"]["current_legs"]}
        winners=[row for row in matrix if row["playerId"] in selected]
        assert len(winners)==2
        assert all(row["failedOverlayGates"]==[] for row in winners)
    finally:
        con.close()


def test_missing_one_real_nested_function_does_not_fake_sixteen_missing_steps(tmp_path):
    con=open_db(str(tmp_path / "tamper-one-function.sqlite"))
    try:
        result=execute(con,snapshot(2),DATE,"CONFIRMED")
        assert result["card"] is not None
        first=con.execute(
            "SELECT game_id,player_id,details FROM gates "
            "WHERE slate_date=? AND stage='CONFIRMED' AND gate='G0' "
            "AND player_id NOT LIKE 'GOALIE_DIRECTION:%' LIMIT 1",
            (DATE,)).fetchone()
        assert first is not None
        payload=json.loads(first["details"])
        original=payload["evidence"]["originalFunctionEvidence"]
        assert any(x["step"]=="Step0" for x in original)
        payload["evidence"]["originalFunctionEvidence"]=[
            x for x in original if x["step"]!="Step0"]
        con.execute(
            "UPDATE gates SET details=? WHERE slate_date=? AND stage='CONFIRMED' "
            "AND game_id=? AND player_id=? AND gate='G0'",
            (json.dumps(payload),DATE,first["game_id"],first["player_id"]))
        diag=explain_live_blockers(con,DATE,"CONFIRMED")
        row=next(x for x in diag["candidateGateMatrix"]
                 if x["gameId"]==first["game_id"] and x["playerId"]==first["player_id"])
        assert row["missingOverlayRecords"]==["Step0"]
        assert row["overlayDispositions"]["Step0"]=="MISSING_FUNCTION_EVIDENCE"
        assert row["overlayPassCount"]==len(OVERLAY)-1
        assert diag["allCandidatesHaveEveryMasterAndOverlayRecord"] is False
    finally:
        con.close()
