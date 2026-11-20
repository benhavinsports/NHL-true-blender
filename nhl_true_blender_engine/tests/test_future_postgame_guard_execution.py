"""A source-validated postgame guard must run in the REAL future scorer engine.

This is intentionally synthetic: no current NHL game or previously frozen
real Core is changed. Only a forged-in-test contradictory PASS is rejected.
"""
import json
from nhl_true_blender_engine import engine
from nhl_true_blender_engine.postgame_recalibration import GUARD_POLICIES
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_end_to_end_contract import fixture, DATE


def test_activated_future_guard_rejects_candidate_before_g16_g18(tmp_path,monkeypatch):
    con=open_db(str(tmp_path/"guard-wired.sqlite"))
    policy=GUARD_POLICIES["G10.5"]
    con.execute("""INSERT INTO patches
        (patch_id,affected_gates,policy,implementation,validation,updated_at)
        VALUES (?,?,?,?,?,?)""",
        (policy, json.dumps(["G10.5"]),
         json.dumps({"gate":"G10.5","activatedAfterSlate":"2026-11-15"}),
         json.dumps({"callable":"apply_active_guards"}),
         json.dumps({"guardReplayTriggered":True,
                     "safeControlRejected":False,
                     "sourcedPregameContradiction":True}),
         "2026-11-16T00:00:00Z"))

    original=engine.evaluate_skater
    def corrupted_pass(*args,**kwargs):
        candidate,traces=original(*args,**kwargs)
        if str(candidate["player"]["id"])=="100" and kwargs.get("defer_g18"):
            # A stored source receipt that claims PASS despite a sourced,
            # undefeated direct recipient is exactly the guarded defect.
            target=next(x for x in traces if x["gate"]=="G10.5")
            assert target["disposition"]=="PASS"
            target["details"]["evidence"]["allAlternativesScanned"]=True
            target["details"]["evidence"]["comparisonRows"]=[
                {"challengerId":"101","status":"RIVAL_DOMINATES"}]
        return candidate,traces
    monkeypatch.setattr(engine,"evaluate_skater",corrupted_pass)

    try:
        result=engine.execute(con,fixture(),DATE,"CONFIRMED")
        assert result["card"] is None
        proof=con.execute("""SELECT disposition,details FROM gates
            WHERE slate_date=? AND stage='CONFIRMED' AND player_id='100'
              AND gate='G10.5'""",(DATE,)).fetchone()
        assert proof is not None
        assert proof["disposition"]=="ELIMINATED"
        details=json.loads(proof["details"])
        assert details["patchEnforcement"]["activatedPatchId"]==policy
        assert details["patchEnforcement"]["reason"]==(
            "PASS_WITH_UNDEFEATED_DIRECT_CHALLENGER")
        assert all(x["playerId"]!="100"
                   for x in result["preCoreQualifiedSurvivors"])
        # Prior real-slate cards are not touched by a future guard test.
        assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]==0
    finally:
        con.close()
