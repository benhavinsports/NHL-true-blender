"""Official final goal recipients versus the ORIGINAL frozen G0/G10.5/G15/G17.

This is an outcome audit, NEVER a hindsight scorer selection or automatic
reversal of a source-backed pregame route. Each official goal is cross-checked
against the NHL boxscore. Only saved pre-puck gates qualify as pregame evidence.
"""
from __future__ import annotations

from datetime import datetime
import json

from .sources import credited_goals_from_pbp, normalize_games, SourceUnavailable
from .storage import get_card

def _time(value):
    if not value:
        return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt if dt.tzinfo else None
    except (ValueError,TypeError):
        return None

def _name(person):
    def string(value):
        if isinstance(value,dict):
            return value.get("default") or ""
        return value if isinstance(value,str) else ""
    return (string(person.get("name")) or
            (string(person.get("firstName"))+" "+string(person.get("lastName"))).strip() or
            "NHL player "+str(person.get("playerId","unknown")))

def pregame_gate(con, date, leg, gate, root="state"):
    """Return the original locked source-backed gate, not later diagnostics."""
    from .postgame_recalibration import _audit_original_gate_proof
    saved=get_card(con,date)
    if saved and gate in ("G0","G10","G10.5","G15","G17"):
        original,origin=_audit_original_gate_proof(
            con,date,saved,leg,root)
        row=original.get(gate)
        if row and origin.get("noMixedGateRuns") is True:
            details=json.loads(row["details"])
            return {"gate":gate,"stage":row["stage"],
                    "status":row["disposition"],
                    "evaluatedAt":row["evaluated_at"],
                    "evidence":details.get("evidence") or {},
                    "sourceIds":details.get("sourceIds") or [],
                    "prePuckOnly":True,
                    "originalGateAuditProvenance":origin}
    prior=[]
    puck=_time(leg.get("startUTC"))
    if puck is None:
        return None
    for row in con.execute("""SELECT gate,stage,disposition,details,evaluated_at
            FROM gates WHERE slate_date=? AND game_id=? AND player_id=? AND gate=?
             AND stage IN ('PROJECTED','CONFIRMED')""",
             (date,str(leg["gameId"]),str(leg["playerId"]),gate)).fetchall():
        measured=_time(row["evaluated_at"])
        if measured is None or measured>=puck:
            continue
        details=json.loads(row["details"])
        prior.append({
            "gate":gate,"stage":row["stage"],
            "status":row["disposition"],
            "evaluatedAt":row["evaluated_at"],
            "evidence":details.get("evidence") or {},
            "sourceIds":details.get("sourceIds") or [],
            "prePuckOnly":True,
        })
    prior.sort(key=lambda x:(x["stage"]=="CONFIRMED",x["evaluatedAt"]),reverse=True)
    return prior[0] if prior else None

def pregame_g0_directions(con,date,game_id,puck_utc):
    """Audit BOTH goalie-first attack directions BEFORE puck drop.

    A single supported target goalie does NOT prove the opposite side was
    evaluated; the other starter might lack a usable NHL EDGE/PBP profile.
    """
    puck=_time(puck_utc)
    if puck is None:
        return []
    result={}
    rows=con.execute("""SELECT stage,player_id,disposition,details,evaluated_at
      FROM gates WHERE slate_date=? AND game_id=? AND gate='G0'
        AND player_id LIKE 'GOALIE_DIRECTION:%'
        AND stage IN ('PROJECTED','CONFIRMED')""",
        (date,str(game_id))).fetchall()
    for row in rows:
        at=_time(row["evaluated_at"])
        if not at or at>=puck:continue
        attacker=row["player_id"].split("GOALIE_DIRECTION:",1)[1]
        detail=json.loads(row["details"])
        ev=detail.get("evidence") or {}
        branch=ev.get("independentGoalieBranches") or []
        d={
            "attackTeam":attacker,
            "defendTeam":ev.get("defender"),
            "sourceProfileEvidenced":row["disposition"]=="PASS",
            "starterStatuses":[x.get("status") for x in branch],
            "goalieIds":[x.get("goalieId") for x in branch],
            "goalieProfileSourceUrls":[x.get("sourceUrl") for x in branch],
            "weakZonesByGoalie":[list((x.get("weakZones") or {}).keys()) for x in branch],
            "sourceReceiptCount":len(detail.get("sourceIds") or []),
            "originalStage":row["stage"],"evaluatedAt":row["evaluated_at"],
            "postgameObservationsNotUsed":True,
        }
        prior=result.get(attacker)
        if not prior or (row["stage"]=="CONFIRMED",at) > (
            prior["originalStage"]=="CONFIRMED",_time(prior["evaluatedAt"])):
            result[attacker]=d
    return sorted(result.values(),key=lambda x:x["attackTeam"])


def compare_official_goal_recipients(card, date, official_games, all_pbp, all_box, gate_reader):
    """Pure adjudication helper to regression test real causality boundaries.

    all_pbp/all_box are game_id => original NHL API receipt objects; neither
    player names nor scores are inferred from the locked card or betting data.
    """
    selection=[]
    for leg in card["current_legs"]:
        game_id=str(leg["gameId"])
        game=official_games.get(game_id)
        if game is None or game.get("gameState") not in ("OFF","FINAL"):
            raise SourceUnavailable("Core game not officially final for retrospective "+game_id)
        pbp=all_pbp[game_id];box=all_box[game_id]
        counts,_=credited_goals_from_pbp(pbp)
        stats=box["data"].get("playerByGameStats") or {}
        observed={}
        for side in ("awayTeam","homeTeam"):
            team_code=game["away"] if side=="awayTeam" else game["home"]
            for pos in ("forwards","defense"):
                for p in (stats.get(side) or {}).get(pos,[]):
                    if p.get("playerId") is None or type(p.get("goals")) is not int:
                        continue
                    pid=str(p["playerId"])
                    if pid in observed:
                        raise SourceUnavailable("Duplicate skater in official boxscore "+pid)
                    observed[pid]={"goals":p["goals"],"player":_name(p),
                                  "team":team_code}
        if not observed:
            raise SourceUnavailable("Official boxscore missing participating skaters "+game_id)
        if not set(counts).issubset(set(observed)):
            raise SourceUnavailable("Official PBP scorer missing from NHL boxscore "+game_id)
        for pid,n in counts.items():
            if observed[pid]["goals"]!=n:
                raise SourceUnavailable("Official PBP/boxscore all-scorer mismatch "+game_id+" "+pid)
        # Roster members who didn't score also require zero in the PBP.
        for pid,p in observed.items():
            if p["goals"]!=counts.get(pid,0):
                raise SourceUnavailable("Official PBP/boxscore disagreement on "+game_id+" "+pid)
        chosen=str(leg["playerId"])
        if chosen not in observed:
            raise SourceUnavailable("Locked scorer absent from official boxscore "+game_id+" "+chosen)
        chosen_team=observed[chosen]["team"]
        g0=gate_reader(leg,"G0")
        g10=gate_reader(leg,"G10")
        g105=gate_reader(leg,"G10.5")
        g15=gate_reader(leg,"G15")
        g17=gate_reader(leg,"G17")
        lookup={}
        if g105 is not None:
            for row in g105["evidence"].get("comparisonRows") or []:
                if row.get("challengerId") is not None:
                    lookup[str(row["challengerId"])]=row
        actual_events=[]
        for p in pbp["data"].get("plays") or []:
            if p.get("typeDescKey")!="goal":continue
            if (p.get("periodDescriptor") or {}).get("periodType")=="SO":continue
            detail=p.get("details") or {}
            if detail.get("scoringPlayerId") is None:
                raise SourceUnavailable("Official goal without scorer ID "+game_id)
            id_=str(detail["scoringPlayerId"])
            actual_events.append({
                "eventId":p.get("eventId"),
                "scorerId":id_,
                "period":(p.get("periodDescriptor") or {}).get("number"),
                "periodType":(p.get("periodDescriptor") or {}).get("periodType"),
                "timeInPeriod":p.get("timeInPeriod"),
                "rinkShotOriginOnly":({
                    "x":detail.get("xCoord"),"y":detail.get("yCoord")}
                    if detail.get("xCoord") is not None and detail.get("yCoord") is not None
                    else None),
                "coordinatesAreNotGoalMouthWeakness":True,
                "officialPlayByPlayUrl":pbp["url"],
            })
        scorers=[]
        for pid,rec in sorted(observed.items(),key=lambda x:(x[1]["team"],x[1]["player"])):
            if rec["goals"]<=0:continue
            rival=lookup.get(pid)
            scorers.append({
                "playerId":pid,"player":rec["player"],"team":rec["team"],
                "goals":rec["goals"],"sameAttackDirectionAsCore":rec["team"]==chosen_team,
                "pregameG105Verdict":rival.get("status") if rival else None,
                "pregameG105ChallengerEvidence":({
                    "candidate":rival.get("candidate"),
                    "challenger":rival.get("challenger"),
                    "sameLane":rival.get("sameLane"),
                    "rivalAlternateGoalieWeakLane":rival.get("rivalAlternateGoalieWeakLane"),
                    "rivalKnownAreas":rival.get("rivalKnownAreas"),
                    "sourceUrls":rival.get("sourceUrls") or [],
                } if rival else None),
                "reasonNotPregameG105Compared":(
                    "OPPOSITE_G0_ATTACK_SIDE" if rec["team"]!=chosen_team else
                    "SAME_TEAM_NOT_IN_SAVED_CHALLENGER_ROWS" if not rival and pid!=chosen
                    else None),
                "notProofPregameDecisionWasCausallyWrong":True,
            })
        selected_goals=observed[chosen]["goals"]
        own_team_goals=sum(x["goals"] for x in observed.values() if x["team"]==chosen_team)
        other_team_goals=sum(x["goals"] for x in observed.values() if x["team"]!=chosen_team)
        false_feeder_claim=bool(g10 and
            g10["evidence"].get("notAssistOrFeeder") is True)
        no_real_later_predictive_proof=bool(g15 and
            g15["evidence"].get("independentFinish") is True and
            not g15["evidence"].get("directFinishEvidenceIndependentOfHistoricalGoalCredit"))
        retrospective_defeated=[x["playerId"] for x in scorers if
            x["team"]==chosen_team and
            x["playerId"]!=chosen and x["pregameG105Verdict"]=="DEFEATED"]
        flags=[]
        if selected_goals==0:
            flags.append("LOCKED_SCORER_DID_NOT_SCORE")
        if retrospective_defeated:
            flags.append("SCORING_TEAMMATE_WAS_PREGAME_G105_DEFEATED_RETROSPECTIVELY")
        if other_team_goals>own_team_goals:
            flags.append("OPPOSITE_G0_DIRECTION_SCORED_MORE_POSTGAME_ONLY")
        if false_feeder_claim:
            flags.append("ORIGINAL_G10_FUTURE_FEEDER_ROLE_WAS_OVERCLAIMED")
        if no_real_later_predictive_proof:
            flags.append("ORIGINAL_G15_WAS_NOT_INDEPENDENT_FINISHER_PROOF")
        selection.append({
            "gameId":game_id,
            "matchup":game["away"]+"@"+game["home"],
            "lockedPlayer":leg["player"],"lockedPlayerId":chosen,
            "lockedPath":leg["path"],
            "lockedTeam":chosen_team,
            "originalOpponentGoalieId":leg.get("opposingGoalieId"),
            "chosenGoals":selected_goals,
            "sameAttackSideGoals":own_team_goals,
            "oppositeAttackSideGoals":other_team_goals,
            "officialScorers":scorers,
            "officialGoalEvents":actual_events,
            "prePuckGateReceipts":{
                "G0":g0,"G10":g10,"G10.5":g105,
                "G15":g15,"G17":g17,
            },
            "retrospectiveGoalScorersMarkedDefeated":retrospective_defeated,
            "auditFlags":flags,
            "officialSources":[pbp["url"],box["url"]],
            "retrospectiveOutcomesNeverBecomePregameEvidence":True,
            "postgameAuditDoesNotClaimGuaranteedAlternative":True,
        })
    return {
        "slateDate":date,"cardId":card["card_id"],
        "originalFingerprint":card["fingerprint"],
        "originalRevision":card["revision"],
        "readOnlyPostgameAudit":True,
        "selectedLegs":selection,
        "missesReviewed":sum(x["chosenGoals"]==0 for x in selection),
        "officialSourceUrls":sorted(set(u for x in selection for u in x["officialSources"])),
        "notAReplacementCard":True,
        "noOutcomeOnlyRulePatch":True,
    }

async def collect_official_recipients(con,date,nhl,root="state"):
    """Re-check every official scorer from the final two NHL data feeds."""
    card=get_card(con,date)
    if not card or not card.get("grade"):
        return {"status":"AWAITING_FROZEN_OFFICIAL_GRADE"}
    raw=await nhl.score(date)
    games={g["id"]:g for g in normalize_games(raw,date)}
    ids={str(x["gameId"]) for x in card["current_legs"]}
    if ids-set(games):
        raise SourceUnavailable("Frozen Core references missing official NHL game")
    for gid in ids:
        if games[gid]["gameState"] not in ("FINAL","OFF"):
            raise SourceUnavailable("Frozen Core has nonfinal official game "+gid)
    pbp={};box={}
    for gid in sorted(ids):
        pbp[gid]=await nhl.play_by_play(gid)
        box[gid]=await nhl.boxscore(gid)
    report=compare_official_goal_recipients(card,date,games,pbp,box,
           lambda leg,gate: pregame_gate(con,date,leg,gate,root=root))
    for leg in report["selectedLegs"]:
        original=next(x for x in card["current_legs"]
                      if str(x["gameId"])==leg["gameId"] and
                         str(x["playerId"])==leg["lockedPlayerId"])
        directions=pregame_g0_directions(con,date,leg["gameId"],original["startUTC"])
        leg["pregameBothG0Directions"]=directions
        complete=len(directions)==2 and all(x["sourceProfileEvidenced"] for x in directions)
        leg["bothGoalieDirectionsWereFullySourceReviewedBeforePuck"]=complete
        if not complete:
            leg["auditFlags"].append("OPPOSING_G0_ATTACK_DIRECTION_NOT_COMPLETELY_SOURCE_REVIEWED")
    return {"status":"OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON",**report}
