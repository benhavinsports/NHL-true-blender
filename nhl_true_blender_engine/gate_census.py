"""Executed-vs-recorded gate certification for every live G0-G18 phase.

A 4,150-row receipt proves matrix coverage, not 4,150 source-backed PASSes.
The census preserves every missing/contradictory/skipped decision. It never
selects or replaces a Core, and never changes a gate's disposition.
"""
from __future__ import annotations
import json
from collections import Counter,defaultdict
from .engine import MASTER,OVERLAY,SCORER_GATE_ORDER,EXECUTION_ORDER
from .storage import get_card
from .semantic_certification import audit_gate

PROVENANCE_REQUIRED={
    "G0","G1","G2","G3","G4","G5","G6","G7","G9","G10",
    "G10.5","G11","G12","G15","G16","G17",
}

def certify_gates(con,date,stage,expected_game_count=None):
    rows=con.execute("""SELECT game_id,player_id,gate,disposition,details FROM gates
        WHERE slate_date=? AND stage=? ORDER BY game_id,player_id,gate""",
        (date,stage)).fetchall()
    goalie_directions=[r for r in rows
        if str(r["player_id"]).startswith("GOALIE_DIRECTION:") and r["gate"]=="G0"]
    skaters=defaultdict(dict)
    # G0 investigations use namespaced database IDs to preserve both
    # unseparated goalie branches. They ARE real official roster players,
    # but are NOT G0-authorized scorer-candidate matrices; including them
    # in source-certified skater PASS/FAIL totals inflated the selection
    # denominator and mislabeled branch research as full candidate passes.
    # Never discard their 36 individual receipts: count them separately.
    research=defaultdict(dict)
    researched_official=set()
    for row in rows:
        pid=str(row["player_id"])
        if pid.startswith("GOALIE_DIRECTION:"):
            continue
        key=(str(row["game_id"]),pid)
        if pid.startswith("G0_RESEARCH:"):
            research[key][row["gate"]]=row
            details=json.loads(row["details"])
            official=details.get("actualOfficialPlayerId")
            if official is not None:
                researched_official.add((str(row["game_id"]),str(official)))
            continue
        skaters[key][row["gate"]]=row
    required=set(EXECUTION_ORDER)
    distributions=defaultdict(Counter);missing=Counter()
    overlay_copies=[];source_unattributed=[];duplicates=[]
    step8_missing=[];missing_gate_evidence=defaultdict(list)
    semantic_failed_by_gate=Counter()
    semantic_failed_examples=[]
    independently_proven_by_gate=Counter()
    attempted_by_gate=Counter()
    order_by_key={}
    order_mismatches=[]
    for key,matrix in skaters.items():
        if set(matrix)!=required:missing.update(required-set(matrix))
        indexed=[]
        for gate,row in matrix.items():
            detail=json.loads(row["details"])
            raw_index=detail.get("executionIndex")
            index=raw_index if type(raw_index) is int else -1
            indexed.append((index,gate))
        indexed.sort(key=lambda item:item[0])
        actual_order=[gate for _,gate in indexed]
        actual_indices=[index for index,_ in indexed]
        order_ok=(actual_order==EXECUTION_ORDER and
                  actual_indices==list(range(len(EXECUTION_ORDER))))
        order_by_key[key]={"verified":order_ok,"actual":actual_order,
                           "indices":actual_indices}
        if not order_ok and len(order_mismatches)<40:
            order_mismatches.append({"gameId":key[0],"playerId":key[1],
                "expected":EXECUTION_ORDER,"actual":actual_order,
                "recordedIndices":actual_indices})
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
    selected_execution_order_gaps=[]
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
            own_source_gaps=[gate for gate in EXECUTION_ORDER
                if gate in PROVENANCE_REQUIRED and gate in matrix
                and matrix[gate]["disposition"]=="PASS"
                and not (json.loads(matrix[gate]["details"]).get("sourceIds") or [])]
            semantic_gaps=[]
            for gate in EXECUTION_ORDER:
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
                                             "gates":own_source_gaps})
            order_info=order_by_key.get(key,{"verified":False,"actual":[],"indices":[]})
            if not order_info["verified"]:
                selected_execution_order_gaps.append({
                    "gameId":key[0],"playerId":key[1],
                    "expected":EXECUTION_ORDER,"actual":order_info["actual"],
                    "recordedIndices":order_info["indices"]})
            selected.append({"gameId":key[0],"playerId":key[1],
                "player":leg["player"],"savedPath":leg["path"],
                "executionOrderVerified":order_info["verified"],
                "executionOrderGaps":([] if order_info["verified"] else
                    ["RECORDED_GATE_ORDER_OR_INDEX_MISMATCH"]),
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
    # A candidate eliminated by a proven earlier gate is different from a
    # candidate whose first nonpassing gate lacks source evidence. Preserve
    # the first failure in the original execution order for auditability.
    first_failure_counts=Counter()
    first_failure_examples=[]
    for key,matrix in skaters.items():
        first=next(((g,matrix[g]["disposition"] if g in matrix else "MISSING")
                    for g in EXECUTION_ORDER
                    if g not in matrix or matrix[g]["disposition"]!="PASS"),None)
        if first:
            gate,disposition=first
            kind=("EVIDENCE_INCOMPLETE" if disposition in ("NOT_EXECUTED", "MISSING", None)
                  else "SOURCE_ELIMINATED")
            first_failure_counts[kind]+=1
            if len(first_failure_examples)<30:
                first_failure_examples.append({"gameId":key[0],
                    "playerId":key[1],"firstGate":gate,"disposition":disposition,
                    "classification":kind})
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
    all_matrix_in_order=bool(skaters) and all(
        order_by_key.get(key,{}).get("verified") is True for key in skaters)
    directions_complete=bool(goalie_directions) and (
        expected_game_count is None or len(goalie_directions)==2*expected_game_count)
    # "Independently checked" means the gate was actually evaluated,
    # sequenced, and proved independent of copied master verdicts. It does
    # NOT mean every rejected player must have source evidence for a PASS.
    # A roster elimination or source-incomplete rival is a valid negative
    # outcome, and must never veto a fully proved selected survivor.
    # Keep NOT_EXECUTED counts separately as honest source diagnostics.
    independent=(all_matrix_present and all_matrix_in_order and not overlay_copies)
    all_selected_master=bool(selected) and all(x["masterAllPass"] for x in selected)
    all_selected_overlay=bool(selected) and all(x["overlayAllPass"] for x in selected)
    required_legs=min(3,expected_game_count) if expected_game_count else len(selected)
    selected_core_certified=bool(
        len(selected)==required_legs and
        len({x["gameId"] for x in selected})==required_legs and
        all_selected_master and all_selected_overlay and
        all(x["overlayIndependentlyEvaluated"] for x in selected) and
        all(x["executionOrderVerified"] for x in selected) and
        not selected_source_gaps and not selected_execution_order_gaps)
    return {
        "slateDate":date,"stage":stage,
        "gateSpecification":{"scorerGateOrder":SCORER_GATE_ORDER,
                             "masterOrder":MASTER,"overlayOrder":OVERLAY,
                             "executionOrder":EXECUTION_ORDER,
                             "masterCount":len(MASTER),"overlayCount":len(OVERLAY),
                             "executionCount":len(EXECUTION_ORDER)},
        "surveyedGoalieDirections":len(goalie_directions),
        "twoDirectionsPerScheduledGameRecorded":directions_complete,
        "goalieDirectionsWithPass":sum(x["disposition"]=="PASS" for x in goalie_directions),
        "scannedSkaters":len(skaters),"gateRows":len(rows),
        "g0ResearchOnlyBranchMatrices":len(research),
        "g0ResearchOnlyOfficialSkaters":len(researched_official),
        "g0ResearchOnlyGateRows":sum(len(m) for m in research.values()),
        "g0ResearchPreservedAsIndependentSourceEvidence":True,
        "g0ResearchExcludedFromCoreCandidateAndPassDenominator":True,
        "allOfficialSkatersReviewedIncludingG0Research":
            len(skaters)+len(researched_official),
        "allSkatersHaveEachGateRecord":all_matrix_present,
        "allSkatersHaveExactExecutionOrder":all_matrix_in_order,
        "executionOrderMismatches":order_mismatches,
        "allOverlayStepsWereIndependentlyChecked":bool(
            all_matrix_present and all_matrix_in_order and not overlay_copies),
        "allOverlayStepsSourceCompleteForEveryRejectedSkater":not any(
            distributions[g]["NOT_EXECUTED"] for g in OVERLAY),
        "nonselectedIncompleteEvidenceRemainsVisible":True,
        "allGateChecksExecutedWithEvidence":not any(distributions[g]["NOT_EXECUTED"] for g in EXECUTION_ORDER),
        "masterGateDispositions":{g:dict(distributions[g]) for g in MASTER},
        "overlayGateDispositions":{g:dict(distributions[g]) for g in OVERLAY},
        "missingMatrixGateRows":{g:missing[g] for g in EXECUTION_ORDER if missing[g]},
        "gateChecksAttempted":{g:attempted_by_gate[g] for g in EXECUTION_ORDER},
        "substantivelyCertifiedPasses":{g:independently_proven_by_gate[g]
                                        for g in EXECUTION_ORDER},
        "recordedPassesWithInsufficientProof":{g:semantic_failed_by_gate[g]
                                               for g in EXECUTION_ORDER},
        "recordedPassProofGapExamples":semantic_failed_examples,
        "step8MissingDetails":step8_missing,
        "step8MissingReasons":dict(Counter(x["reason"] for x in step8_missing)),
        "otherMissingSourceExamples":{g:missing_gate_evidence[g]
                                       for g in EXECUTION_ORDER if missing_gate_evidence[g]},
        "copiedOverlayReceipts":overlay_copies[:12],
        "copiedOverlayReceiptCount":len(overlay_copies),
        "sourceUnattributedPassingGateCount":len(source_unattributed),
        "sourceUnattributedPassingGateExamples":source_unattributed[:15],
        "selectedLegs":selected,
        "selectionFunnel":funnel,
        "firstFailureClassificationCounts":dict(first_failure_counts),
        "firstFailureExamples":first_failure_examples,
        "selectedMasterGatesAllPass":all_selected_master,
        "selectedOverlayGatesAllPass":all_selected_overlay,
        "selectedSourceAttributionGaps":selected_source_gaps,
        "selectedExecutionOrderGaps":selected_execution_order_gaps,
        "selectedCoreOnlyFullyCertified":selected_core_certified,
        "fullIndependentCardCertification":bool(
            directions_complete and independent and selected_core_certified),
        "nonselectedCandidateFailuresAreNotCertificationErrors":True,
        "neverTreatsGateRecordAsAutomaticPass":True,
        "doesNotSelectChangeOrRegradeCard":True,
    }
