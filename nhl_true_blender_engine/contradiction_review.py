"""Real pregame G17 contradiction review, using stored G0/G5/G6/G10.5 sources.

The source-backed review does not arbitrarily resolve incompatible claims:
missing same-lane or lineup evidence remains explicitly unresolved.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
from .engine import all_goalie_branches,challenger_proof,player_releases,release_matched_to_g0_target,receipt,evidence_data
from .enrichment import ingest

SCOPE="DERIVED_CROSS_SOURCE_G17"

def review_all_candidates(con,snapshot,date,stage):
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    created=0;unresolved=0;examples=[]
    for game in snapshot.get("games",[]):
        for attacker,defender in ((game["away"],game["home"]),
                                  (game["home"],game["away"])):
            roster=(game.get("rosters",{}).get(attacker) or {}).get("data",{})
            teammates=roster.get("players",[])
            branches=all_goalie_branches(game,stage).get(defender,[])
            for p in teammates:
                # G17 must review the SAME player-owned route that G5 will
                # evaluate after the goalie-first G0 decision.
                scoped=release_matched_to_g0_target(p,branches[0]) if len(branches)==1 else p
                own=player_releases(scoped)
                if not own or not receipt(scoped.get("release")):
                    continue
                dep=evidence_data(p.get("deployment"))
                opposing=[]
                for b in branches:
                    data=b["data"];weak=data.get("weakZones") or {}
                    strong=data.get("strengthZones") or {}
                    opposing.append({
                        "goalieId":data.get("goalieId"),
                        "starterStatus":data.get("status"),
                        "starterSourceUrl":b["sourceUrl"],
                        "goalieWeakProfileUrl":data.get("goalieProfileSourceUrl"),
                        "sourceKind":data.get("sourceType"),
                        "physicalOriginMatch":own["zone"] in weak,
                        "observedStrongerArea":own["zone"] in strong,
                        "anatomicalPlacementVerified":bool(
                            data.get("anatomicalWeaknessCertified",False)),
                        "observedWeakAreaNames":sorted(weak),
                        "observedStrengthAreaNames":sorted(strong),
                    })
                usable=[b for b in opposing if b["physicalOriginMatch"]]
                rival_ok,rows=challenger_proof(scoped,
                    [x for x in teammates if str(x["id"])!=str(p["id"]) and
                     x.get("availability") not in ("OUT","SCRATCHED","INJURED")],
                    branches[0]["data"].get("weakZones",{}) if len(branches)==1 else {})
                lineup_available=bool(dep and dep.get("EV") and
                        dep.get("status") in ("PROJECTED","CONFIRMED"))
                known_contradiction=any(b["observedStrongerArea"]
                                        for b in usable)
                source_unresolved=(not branches or not usable or
                    not lineup_available or rival_ok is not True or
                    known_contradiction)
                status="UNRESOLVED_CONTRADICTION" if source_unresolved else "CROSS_SOURCE_REVIEW_SATISFIED"
                contradiction={
                    "sourceType":SCOPE,
                    "goalieStrengthReview":{
                        "source":opposing,
                        "sourceScope":"GOALIE_SHOT_ORIGIN_VS_SHOOTER_OWN_AREA",
                        "opposingBranchesReviewed":len(opposing),
                        "strongerAreaContradiction":known_contradiction,
                        "matchedWeakAreas":len(usable),
                    },
                    "lineupDisagreementReview":{
                        "availability":p.get("availability","UNVERIFIED"),
                        "projectedOrConfirmedEV":dep,
                        "lineupSourceUrl":(p.get("deployment") or {}).get("sourceUrl"),
                        "hasProjectedOrConfirmedRole":lineup_available,
                        "isTrulyConfirmed":bool(dep and dep.get("status")=="CONFIRMED"),
                    },
                    "strongestRivalReview":{
                        "everyRivalReviewed":len(rows)==len(teammates)-1-
                            sum(x.get("availability") in ("OUT","SCRATCHED","INJURED")
                                for x in teammates if str(x["id"])!=str(p["id"])),
                        "rivalCompared":len(rows),
                        "eachSameLaneDefeated":rival_ok is True,
                        "rivalResults":rows,
                    },
                    "currentRinkOrigin":own["zone"],
                    "ownReleaseSource":scoped["release"]["sourceUrl"],
                    "outcome":status,
                    "unresolved":source_unresolved,
                    "scope":"observed shot origins, NOT anatomical goal-mouth coordinates",
                    "anatomicalWeaknessCertified":False,
                    "notGoalScoreCertainty":True,
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
                ingest(con,{
                    "evidence_id":f"nhl-contradictions-{date}-{stage}-{game['id']}-{p['id']}-{digest}",
                    "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                    "player_id":str(p["id"]),"kind":"PLAYER_CONTRADICTIONS",
                    "source_url":p["release"]["sourceUrl"],
                    "observed_at":now,"payload":payload})
                created+=1
                if source_unresolved:
                    unresolved+=1
                    if len(examples)<12:
                        examples.append({"gameId":str(game["id"]),"playerId":str(p["id"]),
                            "goalieOriginMatches":len(usable),
                            "lineupAvailable":lineup_available,"rivalRouteDefeated":rival_ok})
    return {"reviewedSkaters":created,"unresolved":unresolved,
            "resolvedFromSourceEvidence":created-unresolved,
            "unresolvedExamples":examples,"independentSourceCrossChecks":True,
            "anatomicalWeaknessCertified":False}
