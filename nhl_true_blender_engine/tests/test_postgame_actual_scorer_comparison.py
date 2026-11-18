"""Official actual scorers are matched to frozen gate verdicts, NOT selected.

Fixtures are deliberately labeled SYNTHETIC; no live result is invented.
"""
from datetime import datetime,timezone
import json
import pytest
from nhl_true_blender_engine.postgame_recipient_audit import (
    compare_official_goal_recipients,pregame_gate)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.sources import SourceUnavailable

DATE="2026-11-15"
ROOT="https://api-web.nhle.com/v1/gamecenter/"
FROST="8480028";BACKLUND="8474150"
BOUCHARD="8480803";DRAISAITL="8477934";MCDAVID="8478402"
ONE="2026020328";TWO="2026020326"

def input_data():
    card={"card_id":"original-nov15-immutable","fingerprint":"original-proof",
          "revision":1,"current_legs":[
              {"gameId":ONE,"playerId":FROST,"player":"Morgan Frost",
               "path":"PRIMARY","startUTC":"2026-11-16T01:00:00Z",
               "opposingGoalieId":"8478024"},
              {"gameId":TWO,"playerId":BOUCHARD,"player":"Evan Bouchard",
               "path":"PRIMARY","startUTC":"2026-11-16T00:30:00Z",
               "opposingGoalieId":"8478435"}]}
    games={ONE:{"id":ONE,"away":"CGY","home":"ANA","gameState":"FINAL"},
           TWO:{"id":TWO,"away":"EDM","home":"PHI","gameState":"OFF"}}
    events={
        ONE:[(BACKLUND,1),(str(8482703),1)],
        TWO:[(DRAISAITL,1),(DRAISAITL,2),(MCDAVID,3)]}
    pbp={}
    for gid,plays in events.items():
        pbp[gid]={"url":ROOT+gid+"/play-by-play",
                  "data":{"plays":[{"typeDescKey":"goal","eventId":i+1,
                    "periodDescriptor":{"number":1,"periodType":"REG"},
                    "timeInPeriod":"12:34",
                    "details":{"scoringPlayerId":int(pid),"xCoord":42,"yCoord":11}}
                    for pid,i in plays]}}
    box={
        ONE:{"url":ROOT+ONE+"/boxscore","data":{"playerByGameStats":{
            "awayTeam":{"forwards":[
                {"playerId":int(FROST),"goals":0,"name":{"default":"Morgan Frost"}},
                {"playerId":int(BACKLUND),"goals":1,"name":{"default":"Mikael Backlund"}}],
                        "defense":[]},
            "homeTeam":{"forwards":[
                {"playerId":8482703,"goals":1,"name":{"default":"Synthetic Duck Scorer"}}],
                        "defense":[]}}}},
        TWO:{"url":ROOT+TWO+"/boxscore","data":{"playerByGameStats":{
            "awayTeam":{"forwards":[
                {"playerId":int(DRAISAITL),"goals":2,"name":{"default":"Leon Draisaitl"}},
                {"playerId":int(MCDAVID),"goals":1,"name":{"default":"Connor McDavid"}}],
                       "defense":[{"playerId":int(BOUCHARD),"goals":0,
                                   "name":{"default":"Evan Bouchard"}}]},
            "homeTeam":{"forwards":[],"defense":[]}}}}
    }
    def gate_reader(leg,gate):
        if gate=="G0":
            return {"gate":gate,"status":"PASS",
                    "evidence":{"attacker":"CGY" if leg["gameId"]==ONE else "EDM"},
                    "sourceIds":[ROOT+leg["gameId"]+"/play-by-play"]}
        if gate=="G10.5":
            target=(BACKLUND if leg["playerId"]==FROST else DRAISAITL)
            rows=[{"challengerId":target,"status":"DEFEATED",
                   "candidate":{"ownedGoals":3 if leg["playerId"]==FROST else 2},
                   "challenger":{"ownedGoals":1 if leg["playerId"]==FROST else 0},
                   "sameLane":True,
                   "sourceUrls":["https://api-web.nhle.com/v1/edge/skater-shot-location-detail/1/now"]}]
            if leg["playerId"]==BOUCHARD:
                rows.append({"challengerId":MCDAVID,"status":"DEFEATED",
                    "sameLane":True,"candidate":{"ownedGoals":2},
                    "challenger":{"ownedGoals":1},"sourceUrls":[ROOT+TWO+"/boxscore"]})
            return {"gate":gate,"status":"PASS","evidence":{"comparisonRows":rows},
                    "sourceIds":[ROOT+leg["gameId"]+"/play-by-play"]}
        if gate=="G10":
            return {"gate":gate,"status":"PASS",
                    "evidence":{"notAssistOrFeeder":True},"sourceIds":[ROOT+ONE+"/boxscore"]}
        if gate=="G15":
            return {"gate":gate,"status":"PASS",
                    "evidence":{"independentFinish":True},"sourceIds":[ROOT+ONE+"/boxscore"]}
        return {"gate":gate,"status":"PASS","evidence":{},"sourceIds":[]}
    return card,games,pbp,box,gate_reader

def test_actual_goal_credit_stays_official_and_old_selected_gate_competitors_marked():
    card,games,pbp,box,gate_reader=input_data()
    result=compare_official_goal_recipients(card,DATE,games,pbp,box,gate_reader)
    assert result["cardId"]==card["card_id"]
    assert result["originalFingerprint"]==card["fingerprint"]
    assert result["originalRevision"]==1
    assert result["notAReplacementCard"] is True
    assert result["missesReviewed"]==2
    frost,bouchard=result["selectedLegs"]
    assert frost["chosenGoals"]==0
    assert frost["sameAttackSideGoals"]==1
    assert frost["oppositeAttackSideGoals"]==1
    assert frost["retrospectiveGoalScorersMarkedDefeated"]==[BACKLUND]
    assert "ORIGINAL_G10_FUTURE_FEEDER_ROLE_WAS_OVERCLAIMED" in frost["auditFlags"]
    assert "ORIGINAL_G15_WAS_NOT_INDEPENDENT_FINISHER_PROOF" in frost["auditFlags"]
    other=next(x for x in frost["officialScorers"] if x["team"]=="ANA")
    assert other["pregameG105Verdict"] is None
    assert other["reasonNotPregameG105Compared"]=="OPPOSITE_G0_ATTACK_SIDE"
    assert bouchard["chosenGoals"]==0
    assert set(bouchard["retrospectiveGoalScorersMarkedDefeated"])=={DRAISAITL,MCDAVID}
    dr=next(x for x in bouchard["officialScorers"] if x["playerId"]==DRAISAITL)
    assert dr["goals"]==2 and dr["pregameG105Verdict"]=="DEFEATED"
    assert dr["notProofPregameDecisionWasCausallyWrong"] is True
    assert len(bouchard["officialGoalEvents"])==3
    assert all(x["coordinatesAreNotGoalMouthWeakness"] for x in bouchard["officialGoalEvents"])
    assert result["noOutcomeOnlyRulePatch"] is True

def test_official_player_credit_disagreement_prevents_publication():
    card,games,pbp,box,gate_reader=input_data()
    box[ONE]["data"]["playerByGameStats"]["awayTeam"]["forwards"][1]["goals"]=0
    with pytest.raises(SourceUnavailable,match="PBP/boxscore"):
        compare_official_goal_recipients(card,DATE,games,pbp,box,gate_reader)

def test_post_puck_gate_receipt_is_not_presented_as_original_pregame(tmp_path):
    con=open_db(str(tmp_path/"original.sqlite"))
    leg={"gameId":ONE,"playerId":FROST,"startUTC":"2026-11-16T01:00:00Z"}
    for stage,at in [("CONFIRMED","2026-11-16T03:01:00Z"),
                     ("PROJECTED","2026-11-15T16:00:00Z")]:
        con.execute("""INSERT INTO gates
             (slate_date,stage,game_id,player_id,gate,disposition,details,evaluated_at)
             VALUES (?,?,?,?,?,?,?,?)""",
             (DATE,stage,ONE,FROST,"G10.5","PASS",
              json.dumps({"evidence":{"stage":stage},
                "sourceIds":[ROOT+ONE+"/boxscore"]}),at))
    result=pregame_gate(con,DATE,leg,"G10.5")
    assert result["stage"]=="PROJECTED"
    assert result["evidence"]["stage"]=="PROJECTED"
    assert result["prePuckOnly"] is True
    con.close()


def test_postgame_scorer_review_prioritizes_original_committed_projected_gate(tmp_path):
    """A frozen, pre-puck original beats later CONFIRMED diagnostics."""
    from nhl_true_blender_engine.engine import MASTER, OVERLAY
    from nhl_true_blender_engine.tests.test_postgame_recalibration import (
        insert_card_and_grade, BEFORE, PREGAME, PUCK)
    con=open_db(str(tmp_path/"receipt.sqlite"))
    insert_card_and_grade(con,DATE)
    con.execute("""INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)""",(
        DATE,"CONFIRMED","8888","888","G10.5","NOT_EXECUTED",
        json.dumps({"evidence":{"stage":"CONFIRMED","allAlternativesScanned":False},
                    "sourceIds":[PREGAME]}),BEFORE))
    order=list(MASTER[:-1])+list(OVERLAY)+["G18"]
    original=[]
    for i,g in enumerate(order):
        original.append({
            "gate":g,"status":"PASS","prePuckRecord":True,
            "recordedExecutionIndex":i,"expectedExecutionIndex":i,
            "executionOrderVerified":True,"evaluatedAt":BEFORE,
            "sourceIds":[PREGAME],
            "evidence":{"stage":"PROJECTED","allAlternativesScanned":True}})
    folder=tmp_path/"site_gates"
    folder.mkdir()
    (folder/f"{DATE}-original-projected.json").write_text(json.dumps({
        "cardId":f"NHL-{DATE}-CANONICAL",
        "fingerprint":"synthetic-fingerprint","revision":1,
        "stage":"PROJECTED","readOnly":True,
        "doesNotSelectOrReplaceScorers":True,
        "executionOrder":order,
        "legs":[{"gameId":"8888","playerId":"888","startUTC":PUCK,
                 "stageOfGateRecords":"PROJECTED",
                 "executionOrderVerified":True,"gateDetails":original}]
    }))
    leg={"gameId":"8888","playerId":"888","startUTC":PUCK}
    result=pregame_gate(con,DATE,leg,"G10.5",root=tmp_path)
    assert result["status"]=="PASS"
    assert result["stage"]=="PROJECTED"
    assert result["evidence"]["stage"]=="PROJECTED"
    assert result["originalGateAuditProvenance"]["receiptType"]=="ORIGINAL_COMMITTED_SOURCE_GATE_EXPORT"
    assert result["originalGateAuditProvenance"]["individualOrderedChecks"]==36
    assert con.execute("SELECT disposition FROM gates WHERE gate='G10.5'").fetchone()[0]=="NOT_EXECUTED"
    con.close()


def test_scratched_locked_scorer_is_valid_official_zero_and_audit_continues():
    card,games,pbp,box,gate_reader=input_data()
    leg=card["current_legs"][0]
    # Remove the locked player from the dressed roster. He has no PBP goal.
    box[ONE]["data"]["playerByGameStats"]["awayTeam"]["forwards"]=[
        p for p in box[ONE]["data"]["playerByGameStats"]["awayTeam"]["forwards"]
        if str(p["playerId"]) != FROST
    ]
    result=compare_official_goal_recipients(card,DATE,games,pbp,box,gate_reader)
    scratched=result["selectedLegs"][0]
    assert scratched["chosenGoals"]==0
    assert scratched["lockedPlayerParticipation"]=="SCRATCHED_OR_NOT_DRESSED_OFFICIAL_ZERO"
    assert scratched["lockedTeam"]=="CGY"
    assert result["missesReviewed"]==2

def test_scratched_locked_scorer_with_pbp_goal_still_fails_closed():
    card,games,pbp,box,gate_reader=input_data()
    box[ONE]["data"]["playerByGameStats"]["awayTeam"]["forwards"]=[
        p for p in box[ONE]["data"]["playerByGameStats"]["awayTeam"]["forwards"]
        if str(p["playerId"]) != FROST
    ]
    pbp[ONE]["data"]["plays"].append({
        "typeDescKey":"goal","eventId":99,
        "periodDescriptor":{"number":3,"periodType":"REG"},
        "timeInPeriod":"01:00","details":{"scoringPlayerId":int(FROST)}
    })
    with pytest.raises(SourceUnavailable,match="absent from official boxscore but credited"):
        compare_official_goal_recipients(card,DATE,games,pbp,box,gate_reader)
