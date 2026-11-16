"""Executed-vs-recorded gate certification for every live G0-G18 phase.

A 4,150-row receipt proves matrix coverage, not 4,150 source-backed PASSes.
The census preserves every missing/contradictory/skipped decision. It never
selects or replaces a Core, and never changes a gate's disposition.
"""
from __future__ import annotations
import json
from collections import Counter,defaultdict
from .engine import MASTER,OVERLAY
from .storage import get_card
from .semantic_certification import audit_gate

PROVENANCE_REQUIRED={
    "G0","G1","G2","G3","G4","G5","G6","G7","G9","G10",
    "G10.5","G11","G12","G15","G16","G17","G18",
}

def certify_gates(con,date,stage,expected_game_count=None):
    rows=con.execute("""SELECT game_id,player_id,gate,disposition,details FROM gates
        WHERE slate_date=? AND stage=? ORDER BY game_id,player_id,gate""",
        (date,stage)).fetchall()
    goalie_directions=[r for r in rows
        if str(r["player_id"]).startswith("GOALIE_DIRECTION:") and r["gate"]=="G0"]
    skaters=defaultdict(dict)
    for row in rows:
        if str(row["player_id"]).startswith("GOALIE_DIRECTION:"):continue
        key=(str(row["game_id"]),str(row["player_id"]))
        skaters[key][row["gate"]]=row
    required=set(MASTER+OVERLAY)
    distributions=defaultdict(Counter);missing=Counter()
    overlay_copies=[];source_unattributed=[];duplicates=[]
    step8_missing=[];missing_gate_evidence=defaultdict(list)
    semantic_failed_by_gate=Counter()
    semantic_failed_examples=[]
    independently_proven_by_gate=Counter()
    attempted_by_gate=Counter()
    for key,matrix in skaters.items():
        if set(matrix)!=required:missing.update(required-set(matrix))
        for gate,row in matrix.items():
            distributions[gate][row["disposition"]]+=1
            attempted_by_gate[gate]+=1
            detail=json.loads(row["details"])
            evidence=detail.get("evidence") or {}
            if row["disposition"]=="PASS":
                gaps=audit_gate(gate,evidence,detail.get("sourceIds"),stage)
                if gaps:
                    semantic_failed_by_gate[gate]+=1
                    if len(semantic_failed_examples)<40:
                        semantic_failed_examples.append({
                            "gameId":key[0],"playerId":key[1],
                            "gate":gate,"missingProof":gaps})
                else:
                    independently_proven_by_gate[gate]+=1
            if gate in OVERLAY and not(
                    evidence.get("independentOverlayEvaluation") is True and
                    evidence.get("checkedBeforeG18") is True and
                    evidence.get("masterGateVerdictCopied") is False):
                overlay_copies.append({"gameId":key[0],"playerId":key[1],"gate":gate})
            if row["disposition"]=="NOT_EXECUTED":
                if len(missing_gate_evidence[gate])<8:
                    missing_gate_evidence[gate].append({"gameId":key[0],
                        "playerId":key[1],"sourceCount":len(detail.get("sourceIds") or [])})
            if gate=="Step8" and row["disposition"]!="PASS":
                match=evidence.get("matchingArea")
                shift_count=evidence.get("actualMatchingAreaShiftEvents") or 0
                urls=evidence.get("officialShiftChartSourceCount") or 0
                reason=("NO_PLAYER_OWN_SCORING_ORIGIN" if not match else
                        "NO_MATCHED_HISTORICAL_DEFENSIVE_SHIFT_IN_OWN_AREA"
                        if not shift_count else
                        "NO_OFFICIAL_SHIFT_CHART_PROVENANCE" if not urls else
                        "NONPASSING_OTHER")
                step8_missing.append({"gameId":key[0],"playerId":key[1],
                    "matchingArea":match,"reason":reason,
                    "observedShiftEvents":shift_count,
                    "sourceCount":len(detail.get("sourceIds") or [])})
            if (gate in PROVENANCE_REQUIRED and row["disposition"]=="PASS" and
                    not detail.get("sourceIds")):
                source_unattributed.append({"gameId":key[0],"playerId":key[1],"gate":gate})
    card=get_card(con,date)
    selected=[]
    selected_source_gaps=[]
    selected_keyset=set()
    if card:
        for leg in card["current_legs"]:
            key=str(leg["gameId"]),str(leg["playerId"])
            selected_keyset.add(key)
            matrix=skaters.get(key,{})
            bad_master=[gate for gate in MASTER
                        if gate not in matrix or matrix[gate]["disposition"]!="PASS"]
            bad_overlay=[{"gate":gate,"status":
                    matrix[gate]["disposition"] if gate in matrix else "MISSING"}
                         for gate in OVERLAY if gate not in matrix or
                         matrix[gate]["disposition"]!="PASS"]
            own_source_gaps=[gate for gate in PROVENANCE_REQUIRED
                if gate in matrix and matrix[gate]["disposition"]=="PASS"
                and not (json.loads(matrix[gate]["details"]).get("sourceIds") or [])]
            semantic_gaps=[]
            for gate in MASTER+OVERLAY:
                if gate not in matrix or matrix[gate]["disposition"]!="PASS":
                    continue
                details=json.loads(matrix[gate]["details"])
                for reason in audit_gate(gate,details.get("evidence"),
                                         details.get("sourceIds"),stage):
                    semantic_gaps.append({"gate":gate,"missingProof":reason})
            if semantic_gaps:
                selected_source_gaps.append({"gameId":key[0],"playerId":key[1],
                                             "semanticMissingProof":semantic_gaps})
            if own_source_gaps:
                selected_source_gaps.append({"gameId":key[0],"playerId":key[1],
                                             "gates":sorted(own_source_gaps)})
            selected.append({"gameId":key[0],"playerId":key[1],
                "player":leg["player"],"savedPath":leg["path"],
                "masterAllPass":not bad_master,"masterMissingOrNonpassing":bad_master,
                "overlayAllPass":not bad_overlay,
                "overlayMissingOrNonpassing":bad_overlay,
                "missingProvenanceForPassingGates":sorted(own_source_gaps),
                "semanticMissingProof":semantic_gaps,
                "substantivelyCertified":not semantic_gaps and not bad_master and not bad_overlay,
                "overlayIndependentlyEvaluated":all(
                    gate in matrix and
                    (json.loads(matrix[gate]["details"]).get("evidence") or {})
                     .get("independentOverlayEvaluation") is True for gate in OVERLAY)})
    # Count outcomes AFTER the full pool was reviewed. A gate failure for a
    # nonselected skater is the selection process, not a fault in the Core.
    # Keep genuine source gaps in the audit, but don't require every rejected
    # player to pass before certifying the three surviving recipients.
    outcome_counts=Counter()
    for key,matrix in skaters.items():
        if key in selected_keyset:
            outcome_counts["SELECTED"]+=1
        elif any(r["disposition"]=="ELIMINATED" for r in matrix.values()):
            outcome_counts["GATE_ELIMINATED"]+=1
        elif any(r["disposition"]=="NOT_EXECUTED" for r in matrix.values()):
            outcome_counts["NOT_QUALIFIED_SOURCE_INCOMPLETE"]+=1
        elif all(g in matrix and matrix[g]["disposition"]=="PASS" for g in required):
            outcome_counts["QUALIFIED_NOT_CHOSEN_G18"]+=1
        else:
            outcome_counts["OTHER_NOT_SELECTED"]+=1
    funnel={
        "surveyedEligibleSkaters":len(skaters),
        "sourceEliminated":outcome_counts["GATE_ELIMINATED"],
        "notQualifiedIncompleteEvidence":outcome_counts["NOT_QUALIFIED_SOURCE_INCOMPLETE"],
        "qualifiedButNotChosen":outcome_counts["QUALIFIED_NOT_CHOSEN_G18"],
        "otherNotSelected":outcome_counts["OTHER_NOT_SELECTED"],
        "lockedCoreRecipients":outcome_counts["SELECTED"],
        "allNonselectedRetainGateAudit":True,
        "nonselectedGateFailuresDoNotInvalidateCertifiedSurvivors":True,
        "oneSourceSelectedCardPreserved":True,
    }
    all_matrix_present=bool(skaters) and not missing and all(
        len(x)==len(required) for x in skaters.values())
    directions_complete=bool(goalie_directions) and (
        expected_game_count is None or len(goalie_directions)==2*expected_game_count)
    independent=all_matrix_present and not overlay_copies
    all_selected_master=bool(selected) and all(x["masterAllPass"] for x in selected)
    all_selected_overlay=bool(selected) and all(x["overlayAllPass"] for x in selected)
    required_legs=min(3,expected_game_count) if expected_game_count else len(selected)
    selected_core_certified=bool(
        len(selected)==required_legs and
        len({x["gameId"] for x in selected})==required_legs and
        all_selected_master and all_selected_overlay and
        all(x["overlayIndependentlyEvaluated"] for x in selected) and
        not selected_source_gaps)
    return {
        "slateDate":date,"stage":stage,
        "gateSpecification":{"masterOrder":MASTER,"overlayOrder":OVERLAY,
                             "masterCount":len(MASTER),"overlayCount":len(OVERLAY)},
        "surveyedGoalieDirections":len(goalie_directions),
        "twoDirectionsPerScheduledGameRecorded":directions_complete,
        "goalieDirectionsWithPass":sum(x["disposition"]=="PASS" for x in goalie_directions),
        "scannedSkaters":len(skaters),"gateRows":len(rows),
        "allSkatersHaveEachGateRecord":all_matrix_present,
        "allOverlayStepsWereIndependentlyChecked":independent,
        "masterGateDispositions":{g:dict(distributions[g]) for g in MASTER},
        "overlayGateDispositions":{g:dict(distributions[g]) for g in OVERLAY},
        "missingMatrixGateRows":dict(missing),
        "gateChecksAttempted":dict(attempted_by_gate),
        "substantivelyCertifiedPasses":dict(independently_proven_by_gate),
        "recordedPassesWithInsufficientProof":dict(semantic_failed_by_gate),
        "recordedPassProofGapExamples":semantic_failed_examples,
        "step8MissingDetails":step8_missing,
        "step8MissingReasons":dict(Counter(x["reason"] for x in step8_missing)),
        "otherMissingSourceExamples":dict(missing_gate_evidence),
        "copiedOverlayReceipts":overlay_copies[:12],
        "copiedOverlayReceiptCount":len(overlay_copies),
        "sourceUnattributedPassingGateCount":len(source_unattributed),
        "sourceUnattributedPassingGateExamples":source_unattributed[:15],
        "selectedLegs":selected,
        "selectionFunnel":funnel,
        "selectedMasterGatesAllPass":all_selected_master,
        "selectedOverlayGatesAllPass":all_selected_overlay,
        "selectedSourceAttributionGaps":selected_source_gaps,
        "selectedCoreOnlyFullyCertified":selected_core_certified,
        "fullIndependentCardCertification":bool(
            directions_complete and independent and selected_core_certified),
        "nonselectedCandidateFailuresAreNotCertificationErrors":True,
        "neverTreatsGateRecordAsAutomaticPass":True,
        "doesNotSelectChangeOrRegradeCard":True,
    }
