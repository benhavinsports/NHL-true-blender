"""Real pregame G17 contradiction review, using stored G0/G5/G6/G10.5 sources.

The source-backed review does not arbitrarily resolve incompatible claims:
missing same-lane or lineup evidence remains explicitly unresolved.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
from .engine import (all_goalie_branches,challenger_proof,player_releases,
                     release_matched_to_g0_target,g0_source_coherent_scorer_goalie,
                     receipt,evidence_data)
from .enrichment import ingest

SCOPE="DERIVED_CROSS_SOURCE_G17"

def review_all_candidates(con,snapshot,date,stage,selected_directions=None,
                          only_player_ids=None,eliminated_player_ids=None,
                          return_receipts=False):
    """Review real independent G17 inputs, including the actual G0 goalie source.

    This independent source review runs at the G17 turn in the engine,
    after the earlier gate decisions have been recorded. G0's independently
    selected attacking side only supplies opponent context; it never supplies
    the contradiction verdict. Preserve incompatible sources as unresolved.
    """
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    created=0;unresolved=0;examples=[]
    returned_receipts={}
    wanted={str(x) for x in only_player_ids} if only_player_ids is not None else None
    eliminated_ids={str(x) for x in (eliminated_player_ids or ())}
    for game in snapshot.get("games",[]):
        decision=(selected_directions or {}).get(str(game["id"]))
        if selected_directions is not None and not decision:
            continue
        directions=((decision["attacker"],decision["defender"]),) if decision else (
            (game["away"],game["home"]),(game["home"],game["away"]))
        for attacker,defender in directions:
            roster=(game.get("rosters",{}).get(attacker) or {}).get("data",{})
            teammates=roster.get("players",[])
            branches=all_goalie_branches(game,stage).get(defender,[])
            if decision:
                # No goalie selected by the reviewer: source coherence applies
                # ONLY to the exact independently selected G0 attacker and
                # official opposing goalie identity.
                branches=[g0_source_coherent_scorer_goalie(game,decision,b)
                          for b in branches]
            for p in teammates:
                if wanted is not None and str(p['id']) not in wanted:
                    continue
                # A separately sourced, already verified independent G17
                # review is authoritative. Do not overwrite it just because
                # another player in this game needs a selected-G0 refresh.
                prior_review=p.get("contradictions")
                if (decision and receipt(prior_review) and
                    (evidence_data(prior_review) or {}).get("sourceType") != SCOPE):
                    returned_receipts[str(p['id'])]=prior_review
                    continue
                # G17 reviews the SAME own-shot route and the SAME goalie+G9
                # exposure as G5/G10.5 for EVERY independently sourced starter
                # branch. Multiple projected starters are not an automatic
                # contradiction if every branch supports one identical route.
                # Never resolve conflicting branches by arbitrarily picking
                # the first reported goalie.
                defense_wrapper=game.get("coverage",{}).get(attacker)
                defending=(defense_wrapper or {}).get("data") or {}
                g9_green=defending.get("greenWeakZones")
                variants=[
                    release_matched_to_g0_target(p,b,defense_wrapper)
                    for b in branches]
                scoped=variants[0] if variants else p
                own=player_releases(scoped)
                if not own or not receipt(scoped.get("release")):
                    continue
                dep=evidence_data(p.get("deployment"))
                rivals=[x for x in teammates
                        if str(x["id"])!=str(p["id"]) and
                        x.get("availability") not in ("OUT","SCRATCHED","INJURED")
                        and str(x["id"]) not in eliminated_ids]
                opposing=[]
                branch_reviews=[]
                rows=[]
                for b,variant in zip(branches,variants):
                    data=b["data"]
                    weak=data.get("weakZones") or {}
                    strong=data.get("strengthZones") or {}
                    route=player_releases(variant)
                    zone=route.get("zone") if route and receipt(variant.get("release")) else None
                    if zone:
                        branch_ok,branch_rows=challenger_proof(
                            variant,rivals,weak,g9_green,
                            opponent_coverage=defending)
                    else:
                        branch_ok,branch_rows=False,[]
                    branch_reviews.append({
                        "goalieId":data.get("goalieId"),
                        "shooterZone":zone,
                        "everyRivalReviewed":len(branch_rows)==len(rivals),
                        "everyDirectRivalDefeated":branch_ok is True,
                        "rivalResults":branch_rows})
                    # Preserve the complete branch-specific challenger evidence.
                    # A different goalie can contradict a rival defeat; never
                    # hide those rows behind the first goalie's comparison.
                    rows.extend([{**item,"opposingGoalieId":data.get("goalieId")}
                                 for item in branch_rows])
                    opposing.append({
                        "goalieId":data.get("goalieId"),
                        "starterStatus":data.get("status"),
                        "starterSourceUrl":b["sourceUrl"],
                        "goalieWeakProfileUrl":data.get("goalieProfileSourceUrl"),
                        "sourceKind":data.get("sourceType"),
                        "ownScoringOrigin":zone,
                        "physicalOriginMatch":bool(zone and zone in weak),
                        "observedStrongerArea":bool(zone and zone in strong),
                        "anatomicalPlacementVerified":bool(
                            data.get("anatomicalWeaknessCertified",False)),
                        "observedWeakAreaNames":sorted(weak),
                        "observedStrengthAreaNames":sorted(strong),
                    })
                usable=[b for b in opposing if b["physicalOriginMatch"]]
                # An unresolved or missing goalie branch is still a genuine
                # source gap. Agreement requires matching own origins in ALL
                # branches as well as successful teammate separation in ALL.
                same_origin=bool(branch_reviews and all(
                    item["shooterZone"]==own["zone"] for item in branch_reviews))
                every_branch_matches=bool(
                    branches and len(usable)==len(branches) and same_origin)
                every_rival_reviewed=bool(
                    branches and len(rows)==len(branches)*len(rivals))
                rival_ok=bool(branch_reviews and all(
                    item["everyDirectRivalDefeated"] and item["everyRivalReviewed"]
                    for item in branch_reviews))
                lineup_available=bool(dep and dep.get("EV") and
                        dep.get("status") in ("PROJECTED","CONFIRMED"))
                known_contradiction=any(b["observedStrongerArea"]
                                        for b in opposing)
                source_unresolved=not (
                    every_branch_matches and every_rival_reviewed and
                    lineup_available and rival_ok and not known_contradiction)
                status="UNRESOLVED_CONTRADICTION" if source_unresolved else "CROSS_SOURCE_REVIEW_SATISFIED"

                contradiction={
                    "sourceType":SCOPE,
                    "goalieStrengthReview":{
                        "source":opposing,
                        "sourceScope":"GOALIE_SHOT_ORIGIN_VS_SHOOTER_OWN_AREA",
                        "opposingBranchesReviewed":len(opposing),
                        "strongerAreaContradiction":known_contradiction,
                        "matchedWeakAreas":len(usable),
                        "everyStarterBranchMatched":every_branch_matches,
                        "sameOwnOriginAcrossStarterBranches":same_origin,
                    },
                    "lineupDisagreementReview":{
                        "availability":p.get("availability","UNVERIFIED"),
                        "projectedOrConfirmedEV":dep,
                        "lineupSourceUrl":(p.get("deployment") or {}).get("sourceUrl"),
                        "hasProjectedOrConfirmedRole":lineup_available,
                        "isTrulyConfirmed":bool(dep and dep.get("status")=="CONFIRMED"),
                    },
                    "strongestRivalReview":{
                        "everyRivalReviewed":every_rival_reviewed,
                        "rivalCompared":len(rows),
                        "eachSameLaneDefeated":rival_ok,
                        "rivalResults":rows,
                        "perGoalieBranchReviews":branch_reviews,
                        "G9OpponentDefenseWeakZonesUsed":list(g9_green) if isinstance(g9_green,list) else None,
                        "matchesG10_5GoalieAndDefenseRouteScope":g9_green is not None,
                    },
                    "currentRinkOrigin":own["zone"],
                    "ownReleaseSource":scoped["release"]["sourceUrl"],
                    "outcome":status,
                    "unresolved":source_unresolved,
                    "scope":"observed shot origins, NOT anatomical goal-mouth coordinates",
                    "anatomicalWeaknessCertified":False,
                    "notGoalScoreCertainty":True,
                    "sameIndependentlySelectedG0GoalieSourceAsScorerG5":
                        bool(decision and len(branches)==1 and
                             usable and len(usable)==1),
                    "G0SelectionDoesNotCopyG17Verdict":True,
                }
                sources=[p["release"]["sourceUrl"]]+[
                    b["goalieWeakProfileUrl"] or b["starterSourceUrl"] for b in opposing]
                if p.get("deployment"):
                    sources.append(p["deployment"]["sourceUrl"])
                payload={**contradiction,"sourceUrls":sorted(set(sources))}
                # Source observations and lineup state may change pre-puck.
                # A fresh reviewed fact is a NEW immutable receipt, never an
                # overwrite of a previous source-linked audit.
                digest=hashlib.sha256(json.dumps(
                    payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:16]
                evidence_id=f"nhl-contradictions-{date}-{stage}-{game['id']}-{p['id']}-{digest}"
                ingest(con,{
                    "evidence_id":evidence_id,
                    "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                    "player_id":str(p["id"]),"kind":"PLAYER_CONTRADICTIONS",
                    "source_url":p["release"]["sourceUrl"],
                    "observed_at":now,"payload":payload})
                returned_receipts[str(p['id'])]={
                    "sourceUrl":p["release"]["sourceUrl"],"observedAt":now,
                    "evidenceId":evidence_id,"data":payload}
                created+=1
                if source_unresolved:
                    unresolved+=1
                    if len(examples)<12:
                        examples.append({"gameId":str(game["id"]),"playerId":str(p["id"]),
                            "goalieOriginMatches":len(usable),
                            "lineupAvailable":lineup_available,"rivalRouteDefeated":rival_ok})
    result={"reviewedSkaters":created,"unresolved":unresolved,
            "resolvedFromSourceEvidence":created-unresolved,
            "unresolvedExamples":examples,"independentSourceCrossChecks":True,
            "anatomicalWeaknessCertified":False}
    if return_receipts:
        result["receipts"]=returned_receipts
    return result
