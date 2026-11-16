"""Source-derived goalie attack lanes and skater owned shot routes from NHL EDGE.

NHL EDGE 'area' is the RINK AREA THE SHOT CAME FROM. It does not contain
the impact coordinate on the net. Consequently, this module never classifies
a glove, blocker, five-hole or specific goal-mouth vulnerability.

Measured data:
- Goalie shots/saves/goals allowed and league save percentage rank by shot origin.
- Skater own shots-on-goal and OWN goals by that same origin.

Inferences, clearly labeled:
- A below-peer shot-origin area is an empirical G0 attack lane.
- A skater's historical goals from that lane support a repeatable route.

Neither inference is a prediction of certainty or a scouting claim about net anatomy.
"""
from __future__ import annotations
import json
import hashlib
from datetime import datetime, timezone
from .enrichment import ingest
from .engine import all_goalie_branches

ORIGIN_METHOD="NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE"
# Conservative evidence floors, NOT scorer rankings or invented gate weights.
# Compare NHL's published goalie savePctgPercentile, not raw league-wide goal totals.
MIN_GOALIE_ZONE_SHOTS=20
MAX_VULNERABLE_SAVE_PCT_PERCENTILE=0.35

def _as_int(v):
    return v if type(v) is int and v>=0 else None

def _record(con,date,stage,game_id,pid,kind):
    row=con.execute("""SELECT payload,source_url,observed_at FROM evidence
            WHERE slate_date=? AND stage=? AND game_id=? AND player_id=? AND kind=?
            ORDER BY observed_at DESC LIMIT 1""",
            (date,stage,str(game_id),str(pid),kind)).fetchone()
    if not row:
        return None
    return {"data":json.loads(row["payload"]),"sourceUrl":row["source_url"],
            "observedAt":row["observed_at"]}

def goalie_rink_weakness(edge):
    """Only evidence-qualified low-peer-percentile goalie shot-origin lanes."""
    if not edge or edge["data"].get("scope")!="NHL_EDGE_SHOT_ORIGIN_RINK_ONLY":
        return None
    weak={}; strong={}; all_zones={}
    for row in edge["data"].get("rinkZoneRows",[]):
        area=row.get("area")
        shots=_as_int(row.get("shotsAgainst"))
        goals=_as_int(row.get("goalsAgainst"))
        saves=_as_int(row.get("saves"))
        percentile=row.get("savePctgPercentile")
        if (not isinstance(area,str) or shots is None or goals is None
                or saves is None or goals+saves!=shots
                or type(percentile) not in (float,int)
                or not 0<=percentile<=1):
            continue
        metrics={"shotsAgainst":shots,"goalsAgainst":goals,"saves":saves,
                 "savePctg":saves/shots if shots else None,
                 "leagueSavePctgPercentile":percentile,
                 "sourceUrl":edge["sourceUrl"],
                 "laneInterpretation":"RINK_SHOT_ORIGIN_NOT_GOAL_MOUTH"}
        all_zones[area]=metrics
        if shots>=MIN_GOALIE_ZONE_SHOTS:
            if percentile<=MAX_VULNERABLE_SAVE_PCT_PERCENTILE and goals>0:
                weak[area]=metrics
            elif percentile>=1-MAX_VULNERABLE_SAVE_PCT_PERCENTILE:
                strong[area]=metrics
    return {
        "weakZones":weak,"strengthZones":strong,
        "totalAreasObserved":len(all_zones),"observedAreas":all_zones,
        "sample":{"qualifiedWeakZoneShots":sum(x["shotsAgainst"] for x in weak.values()),
                  "allZoneObservations":sum(x["shotsAgainst"] for x in all_zones.values())},
        "counterevidence":{
            "otherAreas":{z:v for z,v in all_zones.items() if z not in weak},
            "sampleFloorPerZone":MIN_GOALIE_ZONE_SHOTS,
            "peerPercentileThreshold":MAX_VULNERABLE_SAVE_PCT_PERCENTILE,
            "noGloveBlockerFiveHoleClaim":True,
        },
        "evidenceScope":ORIGIN_METHOD,
        "anatomicalWeaknessCertified":False,
        "weaknessMeaning":"low save-percentile from rink area; cannot assign puck destination",
    }

def skater_owned_routes(edge):
    if not edge or edge["data"].get("scope")!="NHL_EDGE_SHOT_ORIGIN_RINK_ONLY":
        return None
    areas=[]
    for r in edge["data"].get("rinkZoneRows",[]):
        area=r.get("area")
        shots=_as_int(r.get("sog"))
        goals=_as_int(r.get("goals"))
        if not area or shots is None or goals is None or goals>shots or shots==0:
            continue
        areas.append({"zone":area,"sog":shots,"ownedGoals":goals,
                      "sourceUrl":edge["sourceUrl"]})
    if not areas:return None
    # Only own observed goals and shots, no PP bias or player popularity.
    # Highest own historical goals from a named area, then shots; ambiguous
    # equal routes remain visible rather than being discarded.
    areas.sort(key=lambda x:(x["ownedGoals"],x["sog"]),reverse=True)
    top=areas[0]
    tied=[x for x in areas if (x["ownedGoals"],x["sog"])==
                                      (top["ownedGoals"],top["sog"])]
    if len(tied)>1:
        # Do not arbitrarily choose an origin: downstream gate stays unresolved.
        return {"ambiguousRoutes":tied,"allRoutes":areas,
                "sourceType":ORIGIN_METHOD,"canDeterminePrimary":False}
    return {
        "archetype":"OBSERVED_OWN_SHOT_ORIGIN",
        "zone":top["zone"],
        "attempts":top["sog"],
        "ownedGoals":top["ownedGoals"],
        "allRoutes":areas,
        "sourceType":ORIGIN_METHOD,
        "canDeterminePrimary":True,
        "isAnatomicalReleaseClaim":False,
        "isTotalShotAttempts":False,
        "detail":"Shots on goal, not total attempt counts; historical own goals only",
    }

def derive_nhl_edge_attacks(con,snapshot,date,stage):
    """Run after EDGE ingestion, before attaching scout/player evidence.

    Every starter branch from each match is considered independently. A
    profile with no source-backed weak origin areas is not assigned any weakness.
    """
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    goalies=0;skaters=0;ambiguous=0;season_goal_owners=0;zero_shot_owners=0;unresolved=[];goalie_routes={}
    for g in snapshot.get("games",[]):
        id=str(g["id"])
        goalie_routes[id]={}
        for team,branches in all_goalie_branches(g,stage).items():
            goalie_routes[id][team]=[]
            for b in branches:
                d=b["data"];pid=str(d.get("goalieId"))
                if not pid or pid=="None":
                    continue
                source=_record(con,date,stage,id,pid,"NHL_EDGE_GOALIE_RINK_ORIGIN")
                profile=goalie_rink_weakness(source)
                branch_info={
                    "team":team,"goalieId":pid,
                    "starterStatus":d["status"],
                    "starterSource":b["sourceUrl"],
                    "edgeSource":source["sourceUrl"] if source else None,
                    "weakOrigins":sorted(profile["weakZones"]) if profile else [],
                    "anatomicalWeaknessCertified":False,
                }
                goalie_routes[id][team].append(branch_info)
                if not profile or not profile["sample"]["allZoneObservations"]:
                    unresolved.append({"gameId":id,"goalieId":pid,
                        "reason":"NHL EDGE did not provide any source-consistent goalie shot-origin observations"})
                    continue
                if not profile["weakZones"]:
                    unresolved.append({"gameId":id,"goalieId":pid,
                        "reason":"NHL EDGE origin sample did not show a qualified weak area; independently observed no attacking weakness, NOT evidence missing"})
                # Preserve independently observed NHL EDGE strong/no-weak
                # goalie profiles. Previously the lack of a below-peer
                # weak area silently erased the entire OPPOSITE G0 goalie,
                # causing false one-sided attack selection.
                payload={
                    "team":team,"goalieId":pid,"status":d["status"],
                    "weakZones":profile["weakZones"],
                    "strengthZones":profile["strengthZones"],
                    "sample":profile["sample"],
                    "observedAreas":profile["observedAreas"],
                    "sourceReviewed":profile["sample"]["allZoneObservations"]>=MIN_GOALIE_ZONE_SHOTS,
                    "counterevidence":profile["counterevidence"],
                    "sourceType":ORIGIN_METHOD,
                    "sourceClass":"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL",
                    "anatomicalWeaknessCertified":False,
                    "starterSourceUrl":b["sourceUrl"],
                    "method":{"observations":"NHL EDGE goalie shotLocationDetails",
                         "peerComparator":"NHL EDGE savePctgPercentile for each area",
                         "minSOG":MIN_GOALIE_ZONE_SHOTS,
                         "maxPercentile":MAX_VULNERABLE_SAVE_PCT_PERCENTILE,
                         "claim":"observed weaker goalie save percentage from a rink-area origin",
                         "notClaim":"goal-mouth shot placement, glove, blocker, five-hole"},
                }
                digest=hashlib.sha256(json.dumps(payload,sort_keys=True,
                    separators=(",",":")).encode()).hexdigest()[:14]
                ingest(con,{
                    "evidence_id":f"edge-derived-goalie-{date}-{stage}-{id}-{pid}-{digest}",
                    "slate_date":date,"stage":stage,"game_id":id,
                    "kind":"GOALIE_PROFILE","source_url":source["sourceUrl"],
                    "observed_at":now,"payload":payload})
                goalies+=1
        for team in (g["away"],g["home"]):
            roster=(g.get("rosters",{}).get(team) or {}).get("data",{})
            for p in roster.get("players",[]):
                pid=str(p["id"])
                source=_record(con,date,stage,id,pid,"NHL_EDGE_SKATER_RINK_ORIGIN")
                route=skater_owned_routes(source)
                if not route:
                    # Preserve a positive fact from a genuinely complete
                    # NHL EDGE current-season shot-location source: every
                    # reported location has 0 on-net shots AND 0 credited
                    # goals. Such a skater has no observed *direct same-lane*
                    # scoring route to defeat another recipient at G10.5.
                    # This does NOT assert the skater cannot score tonight,
                    # and it never gives that skater a fabricated G4 route.
                    areas=(source or {}).get("data",{}).get("rinkZoneRows",[])
                    observed_zero=bool(areas) and all(
                        type(z.get("sog")) is int and z["sog"]==0 and
                        type(z.get("goals")) is int and z["goals"]==0
                        for z in areas)
                    if observed_zero:
                        zero_payload={
                            "sourceType":"NHL_EDGE_SKATER_SHOT_ORIGIN_CURRENT_SEASON",
                            "allReportedShotOriginsChecked":len(areas),
                            "observedOnNetShotsAcrossAllReportedOrigins":0,
                            "ownedGoalsAcrossAllReportedOrigins":0,
                            "verifiedNoSameLaneOnNetRoute":True,
                            "cannotInferFutureGoal":True,
                            "doesNotQualifyForG4Release":True,
                            "notAnAnatomicalClaim":True
                        }
                        zero_digest=hashlib.sha256(json.dumps(zero_payload,
                            sort_keys=True,separators=(",",":")).encode()).hexdigest()[:14]
                        ingest(con,{
                            "evidence_id":f"edge-zero-shot-route-{date}-{stage}-{id}-{pid}-{zero_digest}",
                            "slate_date":date,"stage":stage,"game_id":id,
                            "player_id":pid,"kind":"PLAYER_ZERO_ON_NET_ROUTE",
                            "source_url":source["sourceUrl"],
                            "observed_at":now,"payload":zero_payload})
                        zero_shot_owners+=1
                    else:
                        unresolved.append({"gameId":id,"skaterId":pid,
                            "reason":"No uniquely attributable own shot-origin source; insufficient for G10.5 dismissal"})
                    continue
                # A tied global primary area is not permission to drop all
                # the skater's measured secondary routes. G0 will first
                # determine the goalie target; G4 may then match one real
                # own zone without guessing which season area was primary.
                if not route.get("canDeterminePrimary"):
                    ambiguous+=1
                else:
                    skaters+=1
                # The existing sampled-eight-game boxscore receipt only proves
                # goals inside THAT sample. A player's earlier official
                # NHL EDGE season goals remain direct OWN scoring evidence,
                # not assists, even when the recent sample contains zero.
                # Never turn zero or missing season goals into a positive.
                own_season_goals=sum(x['ownedGoals'] for x in route.get('allRoutes',[])
                    if isinstance(x.get('ownedGoals'),int) and x['ownedGoals']>=0)
                if own_season_goals>0:
                    credit={
                        "recipient":True,
                        "creditedGoalsVerified":True,
                        "ownedSeasonGoalsFromNhlEdgeShotOrigins":own_season_goals,
                        "independentHistoricallyScored":True,
                        "notClaimOfTonightGoalCredit":True,
                        "verifiedSourceType":"NHL_EDGE_SKATER_GOAL_LOCATION_DETAIL",
                        "scope":"CURRENT_SEASON_GOALS_FROM_MEASURED_AREAS",
                        "notEightGameSample":True,
                        "goalMouthPlacementNotVerified":True,
                    }
                    credit_hash=hashlib.sha256(json.dumps(credit,sort_keys=True,
                        separators=(",",":")).encode()).hexdigest()[:14]
                    ingest(con,{
                        "evidence_id":f"edge-own-goals-{date}-{stage}-{id}-{pid}-{credit_hash}",
                        "slate_date":date,"stage":stage,"game_id":id,
                        "player_id":pid,"kind":"PLAYER_FINISH_CREDIT",
                        "source_url":source["sourceUrl"],
                        "observed_at":now,"payload":credit})
                    season_goal_owners+=1
                route_digest=hashlib.sha256(json.dumps(route,sort_keys=True,
                    separators=(",",":")).encode()).hexdigest()[:14]
                ingest(con,{
                    "evidence_id":f"edge-derived-release-{date}-{stage}-{id}-{pid}-{route_digest}",
                    "slate_date":date,"stage":stage,"game_id":id,"player_id":pid,
                    "kind":"PLAYER_RELEASE","source_url":source["sourceUrl"],
                    "observed_at":now,"payload":route})
    return {
        "method":ORIGIN_METHOD,"goalieProfilesWithMeasuredWeakOrigins":goalies,
        "ownSkaterRoutes":skaters,"ambiguousMultiRouteSkatersKept":ambiguous,
        "allIndependentlyObservedGoalieProfiles":goalies,
        "goaliesWithWeakOrigins":goalies-sum(
            1 for entries in goalie_routes.values() for branches in entries.values()
            for b in branches if b["edgeSource"] and not b["weakOrigins"]),
        "sourceBackedSkaterOwnGoalCredits":season_goal_owners,
        "sourceVerifiedZeroShotRivalProfiles":zero_shot_owners,
        "starterBranches":goalie_routes,
        "unresolvedCount":len(unresolved),"unresolvedExamples":unresolved[:40],
        "anatomicalWeaknessCertified":False,
        "explicitlyInferred":True,
        "source":"https://api-web.nhle.com/v1/edge/",
    }
