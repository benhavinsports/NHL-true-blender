"""Audit actual stored gate traces to distinguish missing source from real elimination.

No scorer ranking, extra Core or fake gate pass. This is a debugging receipt.
"""
import json
from collections import Counter,defaultdict
from .engine import MASTER, OVERLAY, STEPS_BY_GATE

def explain_live_blockers(con,date,stage):
    rows=con.execute("""SELECT game_id,player_id,gate,disposition,details FROM gates
                         WHERE slate_date=? AND stage=? ORDER BY game_id,player_id""",
                     (date,stage)).fetchall()
    players=defaultdict(dict)
    for r in rows:
        if str(r["player_id"]).startswith("GOALIE_DIRECTION:"):continue
        players[(str(r["game_id"]),str(r["player_id"]))][r["gate"]]=r
    totals=Counter();root_causes=defaultdict(Counter);examples=defaultdict(list)
    first_counts=Counter();first_examples=defaultdict(list)
    game_first=defaultdict(Counter)
    game_blockers=defaultdict(list)
    for (game_id,pid),trace in players.items():
        first=next((gate for gate in MASTER if gate not in trace
                    or trace[gate]["disposition"]!="PASS"),"FULL_PASS")
        first_counts[first]+=1
        if len(first_examples[first])<5:first_examples[first].append({"gameId":game_id,"playerId":pid})
        game_first[game_id][first]+=1
        if first in ("G9","G10","G10.5","G17") and len(game_blockers[game_id])<30:
            culprit=trace.get(first)
            proof=json.loads(culprit["details"]).get("evidence",{}) if culprit else {}
            item={"playerId":pid,"firstNonpassingGate":first,
                  "releaseArea":(proof.get("shooterZone") if first=="G9" else None)}
            if first=="G10.5":
                rivals=proof.get("comparisonRows") or []
                item["contradictionStatuses"]=dict(Counter(
                    r.get("status") for r in rivals if r.get("status") not in
                    ("DIFFERENT_TARGET_LANE","DEFEATED")))
                item["firstDirectRivalContradictions"]=[
                    {"id":r.get("challengerId"),"status":r.get("status"),
                     "candidate":r.get("candidate"),"challenger":r.get("challenger")}
                    for r in rivals if r.get("status") not in
                    ("DIFFERENT_TARGET_LANE","DEFEATED")][:3]
            if first=="G9":
                item["opponentWeakAreas"]=proof.get("greenTarget")
            game_blockers[game_id].append(item)
        for gate in ("G4","G5","G6","G9","G10","G10.5","G17"):
            r=trace.get(gate)
            if r is None:
                root_causes[gate]["NO_GATE_RECORD"]+=1;continue
            d=json.loads(r["details"])
            ev=d.get("evidence",{})
            verdict=r["disposition"]
            totals[gate]+=1
            root_causes[gate][verdict]+=1
            if verdict=="PASS":continue
            item={"gameId":game_id,"playerId":pid,"disposition":verdict}
            if gate=="G9":
                item.update(zone=ev.get("shooterZone"),green=ev.get("greenTarget"),
                            red=ev.get("redAvoid"),sourceIds=d.get("sourceIds"))
                subtype=("NO_COVERAGE" if ev.get("greenTarget") is None
                         else "RED_AVOID" if ev.get("shooterZone") in (ev.get("redAvoid") or [])
                         else "NO_MATCHING_GREEN")
            elif gate=="G10.5":
                comparisons=ev.get("comparisonRows") or []
                status=Counter(x.get("status") for x in comparisons)
                item.update(comparisonCounts=dict(status),
                            blockedRivals=[{"id":x.get("challengerId"),"status":x.get("status")}
                                for x in comparisons if x.get("status") not in
                                ("DEFEATED","DIFFERENT_TARGET_LANE")][:14])
                subtype=next((x.get("status") for x in comparisons if x.get("status") not in
                              ("DEFEATED","DIFFERENT_TARGET_LANE")), "MISSING_COMPARISON")
            elif gate=="G17":
                counter=ev.get("counterevidence") or {}
                item.update(sourceType=counter.get("sourceType"),
                            unResolved=counter.get("unresolved"),
                            review=counter.get("outcome"),
                            reason=counter.get("strongestRivalReview",{}).get("eachSameLaneDefeated"))
                subtype=str(counter.get("outcome") or "NO_REVIEW")
            elif gate=="G6":
                item.update(deployment=ev.get("deployment"))
                subtype="NO_EV_LINE" if not (ev.get("deployment") or {}).get("EV") else "UNCONFIRMED_LINE"
            elif gate=="G4":
                item.update(ownRelease=ev.get("ownRelease"))
                subtype="NO_SOURCE_BACKED_SHOOTER_AREA"
            elif gate=="G5":
                item.update(zone=ev.get("shooterZone"),weak=list((ev.get("weakZones") or {})))
                subtype="NO_GOALIE_AREA_OVERLAP"
            else:
                subtype="NOT_PROVEN"
            root_causes[gate]["CAUSE:"+subtype]+=1
            if len(examples[gate])<12:examples[gate].append(item)
    # Preserve the complete player-by-player gate matrix. Aggregate counts
    # alone hid whether G5/G9/G6/G10/G10.5/G17 were failing the SAME players
    # or disjoint candidates; the exact intersection is required to repair G18.
    candidate_matrix=[]
    for (game_id,pid),trace in sorted(players.items()):
        master={g:(trace[g]["disposition"] if g in trace else "MISSING_RECORD")
                for g in MASTER}
        # Step names are original source functions nested in their owning
        # G0-G18 gate, NOT extra rows in the database. Looking for separate
        # Step rows falsely reported EVERY Step missing for EVERY skater.
        embedded={}
        for parent,steps in STEPS_BY_GATE.items():
            row=trace.get(parent)
            parent_evidence=(json.loads(row["details"]).get("evidence") or {}
                             if row is not None else {})
            by_step={item.get("step"):item for item in
                     (parent_evidence.get("originalFunctionEvidence") or [])
                     if isinstance(item,dict)}
            for step in steps:
                found=by_step.get(step)
                embedded[step]=(found.get("disposition","MISSING_FUNCTION_EVIDENCE")
                                if found is not None else
                                "MISSING_PARENT_GATE" if row is None else
                                "MISSING_FUNCTION_EVIDENCE")
        overlay={step:embedded.get(step,"MISSING_FUNCTION_EVIDENCE")
                 for step in OVERLAY}
        failed_master=[g for g,v in master.items() if v!="PASS"]
        failed_overlay=[g for g,v in overlay.items() if v!="PASS"]
        reasons={}
        for gate in set(failed_master+failed_overlay):
            row=trace.get(gate)
            if not row:continue
            detail=json.loads(row["details"]);ev=detail.get("evidence",{})
            if gate=="G5":
                reasons[gate]={"zone":ev.get("shooterZone"),
                               "goalieWeakZones":list(ev.get("weakZones") or {})}
            elif gate=="G6":
                reasons[gate]={"deployment":ev.get("deployment")}
            elif gate=="G9":
                reasons[gate]={"zone":ev.get("shooterZone"),
                    "green":ev.get("greenTarget"),"red":ev.get("redAvoid"),
                    "method":ev.get("coverageComparison"),
                    "zoneConcession":ev.get("zoneConcessionEvidence")}
            elif gate=="G10":
                own=ev.get("goalCreditOwned") or {}
                reasons[gate]={"recipient":own.get("recipient"),
                    "ownedGoalsInActualAppearances":own.get("ownedGoalsInActualAppearances"),
                    "creditedGoalsVerified":own.get("creditedGoalsVerified")}
            elif gate=="G10.5":
                comparisons=ev.get("comparisonRows") or []
                status=Counter(x.get("status") for x in comparisons)
                reasons[gate]={"comparisonCounts":dict(status),
                    "firstDirectContradictions":[
                        {"challengerId":x.get("challengerId"),"status":x.get("status"),
                         "candidate":x.get("candidate"),"challenger":x.get("challenger")}
                        for x in comparisons if x.get("status") not in
                        ("DEFEATED","DIFFERENT_TARGET_LANE")][:3]}
            elif gate=="G17":
                c=ev.get("counterevidence") or {}
                reasons[gate]={"outcome":c.get("outcome"),
                    "unresolved":c.get("unresolved"),
                    "goalieStrengthReview":c.get("goalieStrengthReview"),
                    "lineupDisagreementReview":c.get("lineupDisagreementReview"),
                    "strongestRivalReview":c.get("strongestRivalReview")}
        candidate_matrix.append({
            "gameId":game_id,"playerId":pid,
            "masterPassCount":sum(v=="PASS" for v in master.values()),
            "masterGateCount":len(MASTER),
            "overlayPassCount":sum(v=="PASS" for v in overlay.values()),
            "overlayGateCount":len(OVERLAY),
            "firstNonpassingMasterGate":next((g for g in MASTER if master[g]!="PASS"),None),
            "failedMasterGates":failed_master,
            "failedOverlayGates":failed_overlay,
            "missingMasterRecords":[g for g,v in master.items() if v=="MISSING_RECORD"],
            "missingOverlayRecords":[g for g,v in overlay.items() if v.startswith("MISSING_")],
            "masterDispositions":master,"overlayDispositions":overlay,
            "nonpassReasons":reasons})
    return {"slateDate":date,"stage":stage,"playersEvaluated":len(players),
            "firstNonpassingByOriginalGate":dict(first_counts),
            "firstExamples":dict(first_examples),
            "firstNonpassingGateByGame":{k:dict(v) for k,v in game_first.items()},
            "sourceBlockedCandidatesByGame":dict(game_blockers),
            "gateDispositionAndCauseCounts":{k:dict(v) for k,v in root_causes.items()},
            "actualBlockedSourceExamples":dict(examples),
            "candidateGateMatrix":candidate_matrix,
            "allCandidatesHaveEveryMasterAndOverlayRecord":all(
                not x["missingMasterRecords"] and not x["missingOverlayRecords"]
                for x in candidate_matrix),
            "candidatesPassingAllMasterAndOverlayGates":sum(
                not x["failedMasterGates"] and not x["failedOverlayGates"]
                for x in candidate_matrix),
            "diagnosticOnly":True,"noPlayerRankingOrArtificialGatePass":True}
