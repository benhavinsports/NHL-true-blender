"""Audit actual stored gate traces to distinguish missing source from real elimination.

No scorer ranking, extra Core or fake gate pass. This is a debugging receipt.
"""
import json
from collections import Counter,defaultdict
from .engine import MASTER

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
    return {"slateDate":date,"stage":stage,"playersEvaluated":len(players),
            "firstNonpassingByOriginalGate":dict(first_counts),
            "firstExamples":dict(first_examples),
            "firstNonpassingGateByGame":{k:dict(v) for k,v in game_first.items()},
            "sourceBlockedCandidatesByGame":dict(game_blockers),
            "gateDispositionAndCauseCounts":{k:dict(v) for k,v in root_causes.items()},
            "actualBlockedSourceExamples":dict(examples),
            "diagnosticOnly":True,"noPlayerRankingOrArtificialGatePass":True}
