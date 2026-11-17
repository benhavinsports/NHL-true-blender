"""Independent postgame source-based patch activation and three-slate monthly history.

All test fixtures are SYNTHETIC. They do not assert that a real Nov 15 game
is final, that any player scored, or that an unsupported strategy patch works.
"""
import json
from nhl_true_blender_engine.storage import open_db, encode
from nhl_true_blender_engine.postgame_recalibration import (
    adjudicate_misses,active_guards,apply_active_guards,season_history,
    GUARD_POLICIES)

SOURCE="https://api-web.nhle.com/v1/gamecenter/2026020327/boxscore"
PREGAME="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/888/now"
DATE="2026-11-15"
PUCK="2026-11-16T01:00:00Z"
BEFORE="2026-11-15T15:00:00-05:00"

def insert_card_and_grade(con,date,legs=None,miss=True):
    if legs is None:
        legs=[{"gameId":"8888","playerId":"888","player":"Synthetic Player",
               "path":"PRIMARY","startUTC":PUCK}]
    card_id=f"NHL-{date}-CANONICAL"
    con.execute("""INSERT INTO cards VALUES(?,?,?,?,?,?,?,?,?,?)""",(
        date,card_id,encode(legs),encode(legs),"MIXED",
        "synthetic-fingerprint",1,BEFORE,BEFORE,
        encode({"result":"LOSS" if miss else "WIN"})))
    goals=[{"gameId":x["gameId"],"playerId":x["playerId"],"player":x["player"],
            "goals":0 if miss else 1,"result":"MISS" if miss else "HIT"}
           for x in legs]
    con.execute("""INSERT INTO grades VALUES (?,?,?,?,?,?,?)""",(
        card_id,date,"LOSS" if miss else "WIN",
        encode(goals),encode([SOURCE]),encode([]),BEFORE))
    return card_id

def insert_pregame_gate(con,gate,evidence,disposition="PASS",observed=BEFORE,source=True):
    details={"evidence":evidence,"sourceIds":[PREGAME] if source else []}
    con.execute("""INSERT INTO gates VALUES(?,?,?,?,?,?,?,?)""",(
        DATE,"CONFIRMED","8888","888",gate,disposition,encode(details),observed))

def test_ordinary_official_miss_never_creates_or_activates_a_patch(tmp_path):
    con=open_db(str(tmp_path/"ordinary.sqlite"))
    insert_card_and_grade(con,DATE)
    insert_pregame_gate(con,"G10.5",{
        "allAlternativesScanned":True,
        "comparisonRows":[{"status":"DEFEATED","challengerId":"999"}]})
    insert_pregame_gate(con,"G17",{
        "sourceDerivedReviewResolved":True,
        "counterevidence":{"unresolved":False}})
    insert_pregame_gate(con,"Step8",{"actualShiftByShiftObserved":True})
    result=adjudicate_misses(con,DATE)
    assert result["status"]=="POSTGAME_PATCH_ADJUDICATED"
    assert result["missCount"]==1
    assert result["activated"]==[]
    assert result["decisions"][0]["status"]=="NO_CAUSALLY_PROVEN_PREGAME_GATE_DEFECT"
    assert active_guards(con,"2026-11-16")=={}
    assert con.execute("SELECT COUNT(*) FROM patches").fetchone()[0]==0
    assert adjudicate_misses(con,DATE)["activated"]==[]
    assert con.execute("SELECT COUNT(*) FROM postgame_patch_decisions").fetchone()[0]==1
    con.close()

def test_verified_pregame_contradiction_activates_executable_future_only_guard(tmp_path):
    con=open_db(str(tmp_path/"contradiction.sqlite"))
    insert_card_and_grade(con,DATE)
    contrad={"allAlternativesScanned":True,
             "comparisonRows":[{"challengerId":"999","status":"RIVAL_DOMINATES"}]}
    insert_pregame_gate(con,"G10.5",contrad)
    decision=adjudicate_misses(con,DATE)
    policy=GUARD_POLICIES["G10.5"]
    assert decision["activated"]==[policy]
    assert decision["decisions"][0]["status"]=="AUTOMATIC_GUARD_ACTIVATED"
    assert decision["decisions"][0]["officialSources"]==[SOURCE]
    assert active_guards(con,DATE)=={} # preserve frozen slate
    future=active_guards(con,"2026-11-16")
    assert future=={"G10.5":policy}
    candidate={"complete":True}
    traces=[
      {"gate":"G10.5","disposition":"PASS",
       "details":{"evidence":contrad,"sourceIds":[PREGAME]}},
      {"gate":"G18","disposition":"PASS",
       "details":{"evidence":{"proof":"synthetic"},"sourceIds":[PREGAME]}}
    ]
    got,recs,fired=apply_active_guards(candidate,traces,future)
    assert got["complete"] is False
    assert recs[0]["disposition"]=="ELIMINATED"
    assert recs[1]["disposition"]=="ELIMINATED"
    assert recs[0]["details"]["patchEnforcement"]["activatedPatchId"]==policy
    assert fired[0]["reason"]=="PASS_WITH_UNDEFEATED_DIRECT_CHALLENGER"
    # Ordinary fully defeated recipient remains eligible under same active patch.
    normal={"complete":True}
    passes=[
      {"gate":"G10.5","disposition":"PASS",
       "details":{"evidence":{"allAlternativesScanned":True,
        "comparisonRows":[{"challengerId":"999","status":"DEFEATED"}]},
        "sourceIds":[PREGAME]}},
      {"gate":"G18","disposition":"PASS","details":{"evidence":{},"sourceIds":[PREGAME]}}
    ]
    normal,recs,exclusions=apply_active_guards(normal,passes,future)
    assert normal["complete"] is True
    assert exclusions==[]
    assert all(r["disposition"]=="PASS" for r in recs)
    assert adjudicate_misses(con,DATE)["activated"]==[policy]
    assert con.execute("SELECT COUNT(*) FROM patches").fetchone()[0]==1
    con.close()

def test_after_puck_evidence_or_unsourced_claim_cannot_trigger_patch(tmp_path):
    con=open_db(str(tmp_path/"late.sqlite"))
    insert_card_and_grade(con,DATE)
    insert_pregame_gate(con,"G17",{
        "sourceDerivedReviewResolved":False,
        "counterevidence":{"unresolved":True}},
        observed="2026-11-16T02:00:00Z")
    result=adjudicate_misses(con,DATE)
    assert result["activated"]==[]
    assert active_guards(con,"2026-11-16")=={}
    con.close()

def test_calibration_counts_only_official_frozen_grades_and_three_real_dates_monthly(tmp_path):
    con=open_db(str(tmp_path/"season.sqlite"))
    for n,date in enumerate(["2026-10-07","2026-10-11","2026-10-14",
                              "2026-10-20","2026-10-29","2026-11-15"]):
        insert_card_and_grade(con,date,miss=n%2==0)
    result=season_history(con,2026,"2026-11-15")
    assert result["season"]=="2026-27"
    assert result["officiallyGradedSlates"]==6
    assert result["wins"]==3 and result["losses"]==3
    assert result["legHits"]==3 and result["legOpportunities"]==6
    october=result["monthlyThreeSlateCalibration"]["2026-10"]
    assert october["gradedSlatesAvailable"]==5
    assert october["sampleCount"]==3
    assert [x["date"] for x in october["recalibrationSample"]]==[
        "2026-10-07","2026-10-14","2026-10-29"]
    november=result["monthlyThreeSlateCalibration"]["2026-11"]
    assert november["sampleCount"]==1
    assert len(result["allOfficialGrades"])==6
    assert result["verifiedAutomaticGuardPatches"]==[]
    again=season_history(con,2026,"2026-11-15")
    assert again==result
    assert con.execute("SELECT COUNT(*) FROM season_calibration_history").fetchone()[0]==1
    con.close()


def test_postgame_audits_original_saved_36_gate_card_not_latest_diagnostic(tmp_path):
    """Original source-backed pre-puck contradiction must not be hidden by confirmation."""
    from nhl_true_blender_engine.engine import MASTER, OVERLAY
    con=open_db(str(tmp_path/"historic.sqlite"))
    card_id=insert_card_and_grade(con,DATE)
    # Latest confirmed matrix looks normal, but original immutable source
    # evidence proves a conflicting PASS from the locked projected card.
    insert_pregame_gate(con,"G10.5",{
        "allAlternativesScanned":True,
        "comparisonRows":[{"challengerId":"999","status":"DEFEATED"}]})
    order=list(MASTER[:-1])+list(OVERLAY)+["G18"]
    records=[]
    for i,gate in enumerate(order):
        evidence=({"allAlternativesScanned":True,
                   "comparisonRows":[{"challengerId":"999","status":"RIVAL_DOMINATES"}]}
                  if gate=="G10.5" else {"syntheticGateEvidence":True})
        records.append({
            "gate":gate,"status":"PASS","evidence":evidence,
            "evaluatedAt":BEFORE,"prePuckRecord":True,
            "recordedExecutionIndex":i,"expectedExecutionIndex":i,
            "executionOrderVerified":True,
            "sourceIds":[PREGAME]})
    path=tmp_path/"site_gates"/f"{DATE}-original-projected.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    original={
        "cardId":card_id,"fingerprint":"synthetic-fingerprint","revision":1,
        "stage":"PROJECTED","readOnly":True,
        "doesNotSelectOrReplaceScorers":True,"executionOrder":order,
        "legs":[{"gameId":"8888","playerId":"888","player":"Synthetic Player",
                 "stageOfGateRecords":"PROJECTED","startUTC":PUCK,
                 "executionOrderVerified":True,"gateDetails":records}]
    }
    path.write_text(json.dumps(original))
    result=adjudicate_misses(con,DATE,root=tmp_path)
    assert result["activated"]==[GUARD_POLICIES["G10.5"]]
    decision=result["decisions"][0]
    assert decision["gateAuditProvenance"]["receiptType"]=="ORIGINAL_COMMITTED_SOURCE_GATE_EXPORT"
    assert decision["frozenPregameStage"]=="PROJECTED"
    assert decision["provedPreGameDecisionContradiction"]["reason"]=="PASS_WITH_UNDEFEATED_DIRECT_CHALLENGER"
    # The selected card remains intact; only future pre-proven contradictions
    # are blocked when the guard is active.
    assert con.execute("SELECT fingerprint FROM cards WHERE slate_date=?",(DATE,)).fetchone()[0]=="synthetic-fingerprint"
    con.close()


def test_original_receipt_identity_mismatch_cannot_override_actual_stored_gates(tmp_path):
    """Fabricated/different-card exports are never accepted as gate authority."""
    from nhl_true_blender_engine.engine import MASTER, OVERLAY
    con=open_db(str(tmp_path/"id.sqlite"))
    card_id=insert_card_and_grade(con,DATE)
    insert_pregame_gate(con,"G10.5",{
        "allAlternativesScanned":True,
        "comparisonRows":[{"challengerId":"999","status":"DEFEATED"}]})
    order=list(MASTER[:-1])+list(OVERLAY)+["G18"]
    path=tmp_path/"site_gates"/f"{DATE}-original-projected.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({
        "cardId":card_id,"fingerprint":"wrong-other-card",
        "revision":1,"readOnly":True,
        "doesNotSelectOrReplaceScorers":True,"executionOrder":order,
        "legs":[{"gameId":"8888","playerId":"888","startUTC":PUCK,
                 "executionOrderVerified":True,"gateDetails":[]}]}))
    result=adjudicate_misses(con,DATE,root=tmp_path)
    assert result["activated"]==[]
    assert result["decisions"][0]["gateAuditProvenance"]["receiptType"]=="PARTIAL_CURRENT_DATABASE_RECORDS"
    assert con.execute("SELECT COUNT(*) FROM patches").fetchone()[0]==0
    con.close()


def test_archived_coherent_matrix_checked_when_current_receipts_have_been_replaced(tmp_path):
    """A complete timestamped original archive is used; disjoint PASS rows cannot join."""
    from nhl_true_blender_engine.engine import EXECUTION_ORDER
    con=open_db(str(tmp_path/"cohort.sqlite"))
    insert_card_and_grade(con,DATE)
    insert_pregame_gate(con,"G10.5",{
        "allAlternativesScanned":True,
        "comparisonRows":[{"challengerId":"999","status":"DEFEATED"}]})
    for i,gate in enumerate(EXECUTION_ORDER):
        evidence=({"allAlternativesScanned":True,
                   "comparisonRows":[{"challengerId":"999","status":"RIVAL_DOMINATES"}]}
                  if gate=="G10.5" else {"syntheticFixtureEvidence":True})
        payload=encode({"executionIndex":i,"evidence":evidence,"sourceIds":[PREGAME]})
        con.execute("""INSERT INTO gate_history VALUES (?,?,?,?,?,?,?,?,?,?)""",(
            "synthetic-history-"+gate,DATE,"PROJECTED","8888","888",
            gate,"PASS",payload,BEFORE,BEFORE))
    result=adjudicate_misses(con,DATE)
    assert result["activated"]==[GUARD_POLICIES["G10.5"]]
    provenance=result["decisions"][0]["gateAuditProvenance"]
    assert provenance["receiptType"]=="SAME_EXECUTION_DATABASE_GATE_COHORT"
    assert provenance["databaseOrigin"]=="HISTORY"
    assert provenance["individualOrderedChecks"]==36
    con.close()


def test_season_calibration_records_only_source_verified_original_g0_g105_miss_patterns(tmp_path):
    """Grade history counts official winner/loser, never infers new future scorer."""
    con=open_db(str(tmp_path/"calendar.sqlite"))
    dates=("2026-11-15","2026-11-16")
    for day in dates:
        insert_card_and_grade(con,day,miss=True)
    folder=tmp_path/"site_runs"
    folder.mkdir()
    def audit(day,fingerprint="synthetic-fingerprint"):
        return {
            "status":"OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON",
            "slateDate":day,"cardId":f"NHL-{day}-CANONICAL",
            "originalFingerprint":fingerprint,"originalRevision":1,
            "officialSourceUrls":[SOURCE],
            "selectedLegs":[{
                "gameId":"8888","lockedPlayerId":"888",
                "lockedPlayer":"Synthetic Player","lockedPath":"TRANSFER",
                "lockedTeam":"TEST","chosenGoals":0,
                "sameAttackSideGoals":1,"oppositeAttackSideGoals":3,
                "officialSources":[SOURCE],
                "officialScorers":[{
                    "playerId":"999","player":"Synthetic Teammate","team":"TEST",
                    "goals":1,"sameAttackDirectionAsCore":True,
                    "pregameG105Verdict":"DEFEATED"}]
            }]
        }
    }
    (folder/"2026-11-15-recipient-audit.json").write_text(
        json.dumps(audit("2026-11-15")))
    # A report from a different original Core must NOT affect the sample.
    (folder/"2026-11-16-recipient-audit.json").write_text(
        json.dumps(audit("2026-11-16",fingerprint="OTHER-CARD")))
    report=season_history(con,2026,"2026-11-16",root=tmp_path)
    route=report["officialRouteCalibration"]
    assert report["officiallyGradedSlates"]==2
    assert route["officiallyComparedSlates"]==1
    assert route["originalLegsCompared"]==1
    assert route["scorerMissesCompared"]==1
    assert route["missesWithDefeatedTeammateScorer"]==1
    assert route["missesWithOppositeG0SideScoringMore"]==1
    assert route["observations"][0]["officialSourceUrls"]==[SOURCE]
    assert route["noOddsWeightsOrAutomaticRecipientOverride"] is True
    assert con.execute("SELECT COUNT(*) FROM patches").fetchone()[0]==0
    con.close()
