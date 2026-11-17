"""Read-only user-facing NHL True Blender receipts.

Exports the ONE saved Core and the actual stored G0-G18 + Phase-1 overlay
records for each selected recipient. It never picks players or changes a card.
A gate recorded after puck drop cannot masquerade as its pregame evidence.
Full evidence is retained so UI drilldowns are inspectable, not fake scores.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from .engine import MASTER, OVERLAY, EXECUTION_ORDER
from .storage import get_card

def _datetime(value):
    if not value:
        return None
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d if d.tzinfo else None
    except (ValueError, TypeError):
        return None

def _source(value):
    return {
        "sourceUrl":value.get("sourceUrl"),
        "observedAt":value.get("observedAt"),
        "status":(value.get("data") or {}).get("status")
    } if isinstance(value,dict) and isinstance(value.get("sourceUrl"),str) else None

def _game_summary(game):
    goalies={}
    rosters={}
    coverage={}
    for team in (game.get("away"),game.get("home")):
        branches=[]
        for item in game.get("goalies",{}).get(team,[]) or []:
            data=item.get("data") or {}
            branches.append({
                "goalieId":str(data.get("goalieId")) if data.get("goalieId") is not None else None,
                "status":data.get("status"),
                "weakZones":data.get("weakZones") or {},
                "sourceUrl":item.get("sourceUrl"),
                "observedAt":item.get("observedAt"),
                "profileSourceUrl":data.get("goalieProfileSourceUrl")
            })
        goalies[str(team)]=branches
        roster=(game.get("rosters") or {}).get(team)
        players=(roster or {}).get("data",{}).get("players") or []
        rosterInfo={"rosterPlayers":len(players),
            "sourceUrl":(roster or {}).get("sourceUrl"),
            "observedAt":(roster or {}).get("observedAt"),
            "availabilityReports":{},
            "unavailablePlayers":[],
            "deploymentEvidence":[],
            "recentFormEvidenceCount":0}
        for player in players:
            status=player.get("availability")
            if status:
                rosterInfo["availabilityReports"][status]=rosterInfo["availabilityReports"].get(status,0)+1
            if status in ("OUT","SCRATCHED","INJURED","IR","LTIR","DAY_TO_DAY"):
                rosterInfo["unavailablePlayers"].append({
                    "name":player.get("name"),"status":status})
            deployment=player.get("deployment")
            dep=(deployment or {}).get("data") or {}
            if dep and (dep.get("EV") or dep.get("PP") or dep.get("PK")):
                rosterInfo["deploymentEvidence"].append({
                    "playerId":str(player.get("id")),
                    "name":player.get("name"),
                    "EV":dep.get("EV"),"PP":dep.get("PP"),"PK":dep.get("PK"),
                    "status":dep.get("status"),
                    "sourceUrl":(deployment or {}).get("sourceUrl"),
                    "observedAt":(deployment or {}).get("observedAt")})
            if player.get("gameLog") and player.get("pressure"):
                rosterInfo["recentFormEvidenceCount"]+=1
        rosters[str(team)]=rosterInfo
        area=(game.get("coverage") or {}).get(team)
        d=(area or {}).get("data") or {}
        coverage[str(team)]={
            "sourceUrl":(area or {}).get("sourceUrl"),
            "observedAt":(area or {}).get("observedAt"),
            "greenWeakZones":d.get("greenWeakZones") or [],
            "redStrongZones":d.get("redStrongZones") or [],
            "actualDefensiveShiftMatches":d.get("actualDefensiveShiftMatches"),
            "historicalShiftIsNotTonightLineup":True}
    return {
        "gameId":str(game.get("id")),
        "away":game.get("away"),"home":game.get("home"),
        "matchup":str(game.get("away"))+" @ "+str(game.get("home")),
        "startUTC":game.get("startUTC"),
        "gameState":game.get("gameState"),
        "goaliesByTeam":goalies,
        "rostersByTeam":rosters,
        "defenseByAttackingTeam":coverage,
        "summaryIsNotConfirmedDeployment":True,
    }

def export_dashboard(con,date,stage,snapshot,root="state"):
    root=Path(root)
    card=get_card(con,date)
    payload={
        "slateDate":date,
        "stage":stage,
        "cardId":card["card_id"] if card else None,
        "fingerprint":card["fingerprint"] if card else None,
        "revision":card["revision"] if card else None,
        "readOnly":True,
        "doesNotSelectOrReplaceScorers":True,
        "games":[_game_summary(g) for g in snapshot.get("games",[])],
        "masterOrder":MASTER,
        "overlayOrder":OVERLAY,
        "executionOrder":EXECUTION_ORDER,
        "legs":[],
    }
    if card:
        for leg in card["current_legs"]:
            gameId,playerId=str(leg["gameId"]),str(leg["playerId"])
            puck=_datetime(leg.get("startUTC"))
            # A confirmed run may have projected evidence for some starting
            # goalies; do not automatically promote that source to CONFIRMED.
            stages=("CONFIRMED","PROJECTED") if stage=="CONFIRMED" else (
                "PROJECTED","CONFIRMED")
            # The saved card is the authority.  A later CONFIRMED review
            # may have source gaps, but must not replace the original 36/36
            # PROJECTED selection receipts with an incomplete phase.
            # Keep both phase outcomes separately; choose the strongest
            # *actual pre-puck* certified trace for the published card.
            phase_rows={}
            phase_reviews={}
            for selectedStage in ("PROJECTED","CONFIRMED"):
                candidates=con.execute("""
                    SELECT gate,disposition,details,evaluated_at
                    FROM gates WHERE slate_date=? AND stage=?
                        AND game_id=? AND player_id=?""",
                    (date,selectedStage,gameId,playerId)).fetchall()
                phase_rows[selectedStage]=candidates
                pre_puck={}
                for row in candidates:
                    checked=_datetime(row["evaluated_at"])
                    if checked and (puck is None or checked<puck):
                        pre_puck[row["gate"]]=row
                complete=(set(pre_puck)==set(EXECUTION_ORDER)
                    and all(pre_puck[gate]["disposition"]=="PASS"
                        and json.loads(pre_puck[gate]["details"]).get(
                            "executionIndex")==index
                        for index,gate in enumerate(EXECUTION_ORDER)))
                phase_reviews[selectedStage]={
                    "available":bool(candidates),
                    "prePuckGateRows":len(pre_puck),
                    "masterPassed":sum(gate in MASTER and
                        row["disposition"]=="PASS"
                        for gate,row in pre_puck.items()),
                    "overlayPassed":sum(gate in OVERLAY and
                        row["disposition"]=="PASS"
                        for gate,row in pre_puck.items()),
                    "fullOriginalOrderPass":complete,
                    "nonpassingGates":{gate:pre_puck[gate]["disposition"]
                        if gate in pre_puck else "NO_PREPUCK_RECEIPT"
                        for gate in EXECUTION_ORDER
                        if gate not in pre_puck or
                        pre_puck[gate]["disposition"]!="PASS"},
                }
            # Prefer fully evidenced CONFIRMED when available, then fully
            # evidenced PROJECTED. Never equate a newer incomplete trace
            # with a replacement or promotion of original source evidence.
            stages_to_check=(("CONFIRMED","PROJECTED") if stage=="CONFIRMED"
                             else ("PROJECTED","CONFIRMED"))
            sourceStage=next((s for s in stages_to_check
                if phase_reviews[s]["fullOriginalOrderPass"]),None)
            if sourceStage is None:
                sourceStage=next((s for s in stages_to_check
                    if phase_reviews[s]["available"]),None)
            realRows=phase_rows.get(sourceStage,[])
            mapping={}
            for row in realRows:
                evaluated=row["evaluated_at"]
                check=_datetime(evaluated)
                if puck and (not check or check>=puck):
                    # After-puck re-evaluations may still be stored as audit,
                    # but they cannot certify the original pregame decision.
                    continue
                details=json.loads(row["details"])
                mapping[row["gate"]]={
                    "gate":row["gate"],
                    "status":row["disposition"],
                    "sourceIds":details.get("sourceIds") or [],
                    "evidence":details.get("evidence") or {},
                    "appliedPatches":details.get("appliedPatches") or [],
                    "evaluatedAt":evaluated,
                    "prePuckRecord":True,
                    "recordedExecutionIndex":details.get("executionIndex"),
                    "executionPhase":details.get("executionPhase"),
                }
            ordered=[]
            for expected_index,gate in enumerate(EXECUTION_ORDER):
                record=mapping.get(gate)
                if record is None:
                    record={"gate":gate,"status":"NO_PREPUCK_RECEIPT",
                            "sourceIds":[],"evidence":{},
                            "prePuckRecord":False,
                            "recordedExecutionIndex":None,
                            "executionPhase":None}
                record["expectedExecutionIndex"]=expected_index
                record["executionOrderVerified"]=(
                    record.get("recordedExecutionIndex")==expected_index)
                ordered.append(record)
            order_verified=all(r["executionOrderVerified"] for r in ordered)
            payload["legs"].append({
                "gameId":gameId,"playerId":playerId,"player":leg["player"],
                "originalLockedPath":leg["path"],
                "stageOfGateRecords":sourceStage,
                "latestReviewStage":stage,
                "separatePhaseReviews":phase_reviews,
                "startUTC":leg.get("startUTC"),
                "executionOrderVerified":order_verified,
                "masterPassed":sum(r["gate"] in MASTER and r["status"]=="PASS"
                                   for r in ordered),
                "overlayPassed":sum(r["gate"] in OVERLAY and r["status"]=="PASS"
                                    for r in ordered),
                "totalMaster":len(MASTER),
                "totalOverlay":len(OVERLAY),
                "sourceVerifiedPregameGateCount":sum(r["status"]=="PASS" and
                    r["prePuckRecord"] for r in ordered),
                "gateDetails":ordered,
            })
    output=root/"site_gates"/f"{date}.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix(".tmp")
    temp.write_text(json.dumps(payload,sort_keys=True,indent=2,default=str)+"\n",
                    encoding="utf-8")
    temp.replace(output)
    return {"path":str(output),"gameCount":len(payload["games"]),
        "cardId":payload["cardId"],"selectedLegCount":len(payload["legs"]),
        "selectedGateRecordCount":sum(leg["sourceVerifiedPregameGateCount"]
           for leg in payload["legs"])}
