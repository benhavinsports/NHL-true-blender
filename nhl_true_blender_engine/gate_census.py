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
    for key,matrix in skaters.items():
        if set(matrix)!=required:missing.update(required-set(matrix))
        for gate,row in matrix.items():
            distributions[gate][row["disposition"]]+=1
            detail=json.loads(row["details"])
            evidence=detail.get("evidence") or {}
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
    if card:
        for leg in card["current_legs"]:
            key=str(leg["gameId"]),str(leg["playerId"])
            matrix=skaters.get(key,{})
            bad_master=[gate for gate in MASTER
                        if gate not in matrix or matrix[gate]["disposition"]!="PASS"]
            bad_overlay=[{"gate":gate,"status":
                    matrix[gate]["disposition"] if gate in matrix else "MISSING"}
                         for gate in OVERLAY if gate not in matrix or
                         matrix[gate]["disposition"]!="PASS"]
            selected.append({"gameId":key[0],"playerId":key[1],
                "player":leg["player"],"savedPath":leg["path"],
                "masterAllPass":not bad_master,"masterMissingOrNonpassing":bad_master,
                "overlayAllPass":not bad_overlay,
                "overlayMissingOrNonpassing":bad_overlay,
                "overlayIndependentlyEvaluated":all(
                    gate in matrix and
                    (json.loads(matrix[gate]["details"]).get("evidence") or {})
                     .get("independentOverlayEvaluation") is True for gate in OVERLAY)})
    all_matrix_present=bool(skaters) and not missing and all(
        len(x)==len(required) for x in skaters.values())
    directions_complete=bool(goalie_directions) and (
        expected_game_count is None or len(goalie_directions)==2*expected_game_count)
    independent=all_matrix_present and not overlay_copies
    all_selected_master=bool(selected) and all(x["masterAllPass"] for x in selected)
    all_selected_overlay=bool(selected) and all(x["overlayAllPass"] for x in selected)
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
        "step8MissingDetails":step8_missing,
        "step8MissingReasons":dict(Counter(x["reason"] for x in step8_missing)),
        "otherMissingSourceExamples":dict(missing_gate_evidence),
        "copiedOverlayReceipts":overlay_copies[:12],
        "copiedOverlayReceiptCount":len(overlay_copies),
        "sourceUnattributedPassingGateCount":len(source_unattributed),
        "sourceUnattributedPassingGateExamples":source_unattributed[:15],
        "selectedLegs":selected,
        "selectedMasterGatesAllPass":all_selected_master,
        "selectedOverlayGatesAllPass":all_selected_overlay,
        "fullIndependentCardCertification":bool(
            directions_complete and independent and all_selected_master and
            all_selected_overlay and not source_unattributed),
        "neverTreatsGateRecordAsAutomaticPass":True,
        "doesNotSelectChangeOrRegradeCard":True,
    }
