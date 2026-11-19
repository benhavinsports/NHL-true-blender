"""Opponent defensive shot-origin concessions from actual NHL play-by-play.

Uses 8 pre-slate historical team games, actual shot ownership and official rink
coordinates. Zones are conservative PROXY bins, not the NHL EDGE exact zone
polygons or goal-mouth placement. A goalie's low save% cannot masquerade as
independent TEAM COVERAGE; this adapter uses distinct defensive-game receipts.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime,timezone
from statistics import median
import hashlib
import json
from .enrichment import ingest

BIN_SPEC="NHL_RINK_COORDINATE_APPROXIMATION_V1"
MIN_DEFENSE_SOURCE_SHOTS=120
MIN_ZONE_SHOTS=16
MIN_ZONE_ON_NET_SHOTS=12

def conservative_zone(x,y):
    if type(x) not in (float,int) or type(y) not in (float,int):
        return None
    ax,ay=abs(float(x)),abs(float(y))
    if ax>100 or ay>43:
        return None
    # Standard NHL rink goals approximately 89 feet from center ice.
    # Only regions with unambiguous distances from center are mapped;
    # no false left/right circle mapping across alternating orientations.
    if 72<=ax<=89 and ay<=14:
        return "Low Slot"
    if 54<=ax<72 and ay<=14:
        return "High Slot"
    if 25<=ax<54 and ay<=35:
        return "Point"
    return None


def detailed_shot_origin_zone(x,y):
    """Conservative NHL PBP x/y-derived circle / point subareas.

    Unlike NHL EDGE tracking polygons, raw PBP x/y are arena-frame estimates
    and cannot establish exact tracking-area membership or goal-mouth impact.
    The shooting side is oriented so its attacking net has positive x.
    This mapping is a labelled approximation, validated from source coords.
    """
    if type(x) not in (float,int) or type(y) not in (float,int):
        return None
    x=float(x);y=float(y)
    ax,ay=abs(x),abs(y)
    if ax>100 or ay>43 or ax<25 or x==0 or y==0:
        return None
    # In NHL rink Cartesian coordinates, the attacking net is at ±89.
    # For an attacking end at -89, mirror both raw x and y axes.
    # Left/right is perspective-normalized, not a claimed goalie glove side.
    left=(x*y)>0
    if 54<=ax<78 and 15<=ay<=35:
        return "L Circle" if left else "R Circle"
    if 25<=ax<54 and ay<=35:
        if ay<=12:
            return "Center Point"
        return "L Point" if left else "R Point"
    return None


def summarize_concessions(events,game_meta):
    """Count ALL opponent shot attempts by rink origin, not only on-net shots."""
    by_team=defaultdict(lambda:{
        "totalAttempts":0,"totalShots":0,"goalsAgainst":0,
        "bins":defaultdict(int),"onNetBins":defaultdict(int),
        "goalBins":defaultdict(int),"gameIds":set(),"sourceUrls":set()})
    seen=set()
    for e in events:
        if e.get("type") not in ("goal","shot-on-goal","missed-shot","blocked-shot"):
            continue
        game=game_meta.get(str(e.get("gameId")))
        if not game:
            continue
        owner=str(e.get("ownerTeamId") or "")
        home=str(game.get("homeTeamId") or "")
        away=str(game.get("awayTeamId") or "")
        if not home or not away or owner not in (home,away):
            continue
        eid=(str(e["gameId"]),str(e["eventId"]))
        if eid in seen:
            continue
        seen.add(eid)
        defender=away if owner==home else home
        row=by_team[defender]
        row["totalAttempts"]+=1
        row["gameIds"].add(str(e["gameId"]))
        if e.get("type") in ("goal","shot-on-goal"):
            row["totalShots"]+=1
        if e.get("type")=="goal":
            row["goalsAgainst"]+=1
        # Every shot-attempt event is counted once. Coordinates are rink
        # origin proxies; a blocked/missed attempt is not an on-net shot.
        region=conservative_zone(e.get("x"),e.get("y"))
        detail=detailed_shot_origin_zone(e.get("x"),e.get("y"))
        for zone in {z for z in (region,detail) if z}:
            row["bins"][zone]+=1
            if e.get("type") in ("goal","shot-on-goal"):
                row["onNetBins"][zone]+=1
            if e.get("type")=="goal":
                row["goalBins"][zone]+=1
        if e.get("sourceUrl"):
            row["sourceUrls"].add(e["sourceUrl"])
    return by_team

def make_coverage(con,snapshot,date,stage,events,game_meta,shift_receipts=None, *, historical_replay_observed_at=None):
    # Identify the current slate franchise by its ID on a verified historical
    # scheduled game, not guessed abbreviation strings.
    abbr_to_id={}
    for data in game_meta.values():
        for side in ("home","away"):
            abbrev=data.get(side+"Abbrev")
            pid=data.get(side+"TeamId")
            if abbrev and pid:
                abbr_to_id[abbrev]=str(pid)
    by_team=summarize_concessions(events,game_meta)
    # Compare each target club with OTHER clubs only. A lower share/rate of
    # shots from an area is not proof that its defense is strong there.
    minimum_peer_attempts=MIN_DEFENSE_SOURCE_SHOTS
    minimum_peer_games=6
    minimum_zone_attempts=MIN_ZONE_SHOTS
    now=(historical_replay_observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds"))
    count=0;fail=[]
    for game in snapshot.get("games",[]):
        for attacker,defender in ((game["away"],game["home"]),(game["home"],game["away"])):
            pid=abbr_to_id.get(defender)
            row=by_team.get(pid) if pid else None
            if (not row or row["totalAttempts"]<minimum_peer_attempts
                    or len(row["gameIds"])<minimum_peer_games):
                fail.append({"gameId":str(game["id"]),"defender":defender,
                            "reason":"Not enough independently sourced historical shot attempts across six games"})
                continue
            green={};red={};detail={}
            for z in ("Low Slot","High Slot","Point","L Circle","R Circle",
                      "L Point","R Point","Center Point"):
                peers=[]
                peer_on_net=[]
                for peer_id,peer in by_team.items():
                    if peer_id==pid:
                        continue
                    games=len(peer["gameIds"])
                    if (peer["totalAttempts"]<minimum_peer_attempts
                            or games<minimum_peer_games):
                        continue
                    peers.append(peer["bins"].get(z,0)/games)
                    peer_on_net.append(peer["onNetBins"].get(z,0)/games)
                if len(peers)<6 or len(peer_on_net)!=len(peers):
                    continue
                peer_median=median(peers)
                peer_on_net_median=median(peer_on_net)
                attempts=row["bins"].get(z,0)
                games=len(row["gameIds"])
                per_game=attempts/games
                on_net=row["onNetBins"].get(z,0)
                goals=row["goalBins"].get(z,0)
                info={
                    "attemptsAgainst":attempts,
                    "onNetShotsAgainst":on_net,
                    "goalsAgainst":goals,
                    "allAttemptsAgainst":row["totalAttempts"],
                    "allOnNetShotsAgainst":row["totalShots"],
                    "attemptsPerGame":per_game,
                    "peerMedianAttemptsPerGame":peer_median,
                    "onNetShotsPerGame":on_net/games,
                    "peerMedianOnNetShotsPerGame":peer_on_net_median,
                    "attemptShare":attempts/row["totalAttempts"],
                    "gameCount":games,
                    "peerTeamsCompared":len(peers),
                    "classification":BIN_SPEC,
                    "attemptTypes":["goal","shot-on-goal","missed-shot","blocked-shot"],
                }
                # G9 has TWO physical, separately measured positive ways an
                # opponent actually permits shots in the skater's own origin:
                # all attempted shots OR shots that reached the goalie.
                # The old one-metric path discarded a real attack lane when
                # blocked/missed attempts were merely lower than peers, even
                # though independently recorded on-net concessions were HIGH.
                # Neither path uses the opposing GOALIE's saves, market odds,
                # player reputation, or a proxy red/strong-defense verdict.
                attempt_supported=(attempts>=minimum_zone_attempts and
                                   per_game>peer_median)
                on_net_supported=(on_net>=MIN_ZONE_ON_NET_SHOTS and
                                  on_net/games>peer_on_net_median)
                info["positiveConcessionBases"]=(
                    (["ATTEMPTS_AGAINST_PEER"] if attempt_supported else [])+
                    (["ON_NET_SHOTS_AGAINST_PEER"] if on_net_supported else []))
                info["independentOnNetConcessionReview"]=True
                detail[z]=info
                if attempt_supported or on_net_supported:
                    green[z]=info
            urls=sorted(row["sourceUrls"])
            shift_team=(shift_receipts or {}).get("byDefendingTeamId",{}).get(pid,{})
            observed_shift_events=list(shift_team.get("sampleEvents") or [])
            shift_sources=sorted(shift_team.get("shiftSourceUrls") or [])
            payload={"attackingTeam":attacker,"defendingTeam":defender,
                "sourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
                "greenWeakZones":list(green),"redStrongZones":list(red),
                "zoneConcessions":detail,
                "comparison":"RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN",
                "additionalPositiveEvidenceMethod":"RECENT_OPPONENT_ON_NET_SHOTS_PER_GAME_VS_OTHER_TEAM_MEDIAN",
                "method":BIN_SPEC,
                "derivedCirclePointAreas":True,
                "derivedAreasNotExactNhlEdgeTrackingPolygons":True,
                "coordinateSystem":"NHL_PBP_ARENA_FRAME_ORIENTED_TO_ATTACKING_NET",
                "noGloveBlockerFiveHoleInterpretation":True,
                "comparisonSampleTeams":sum(bool(q) for q in by_team.values()),
                "trackedGameIds":sorted(row["gameIds"]),
                "sourceUrls":urls,
                "shiftByShift":observed_shift_events,
                "shiftSourceUrls":shift_sources,
                "shiftChartGameIds":shift_team.get("sourceGameIds",[]),
                "shiftEventCountByZone":shift_team.get("zoneEvents",{}),
                "actualDefensiveShiftMatches":shift_team.get("matchedEvents",0),
                "shiftCoverageProvenance":"OFFICIAL_NHL_SHIFTCHARTS_AND_HISTORICAL_PBP",
                "historicalShiftsNotTonightDeployment":True,
                "onIcePlayerPositionsNotAssumed":True,
                "inferredLaneNotExactNhlEdgePolygon":True,
                "lowShotVolumeIsNotEvidenceOfDefensiveStrength":True,
                "redZonesRequireIndependentPositiveDefensiveEvidence":True,
                "historicalReconstruction":historical_replay_observed_at is not None,
                "historicalSourceObservedAtCutoffVerified":False if historical_replay_observed_at else None,
                "replayAvailabilityClockBasis":"OFFICIAL_GAME_START_PLUS_SIX_HOURS" if historical_replay_observed_at else None,
                "unobservedAreasNotAssignedGreen":True}
            if urls:
                version=hashlib.sha256(json.dumps(payload,sort_keys=True,
                    separators=(",",":")).encode()).hexdigest()[:16]
                ingest(con,{
                    "evidence_id":f"nhl-team-coverage-{date}-{stage}-{game['id']}-{attacker}-{version}",
                    "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                    "kind":"TEAM_COVERAGE","source_url":urls[0],
                    "observed_at":now,"payload":payload})
                count+=1
    return {"coverageAttackSides":count,
            "targetSides":2*len(snapshot.get("games",[])),
            "peerComparison":"OTHER_TEAM_MEDIAN_SHOT_ATTEMPTS_PER_GAME",
            "minimumPeerAttempts":minimum_peer_attempts,
            "minimumPeerGames":minimum_peer_games,
            "minimumZoneAttempts":minimum_zone_attempts,
             "minimumZoneOnNetShots":MIN_ZONE_ON_NET_SHOTS,
            "failedSources":fail[:15],
            "sourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
            "zonesAreConservativeDerivedRinkAreas":True,
            "lowShotVolumeNeverCreatesRedStrengthZone":True,
            "officialShiftChartGames":(shift_receipts or {}).get("chartedGames",0),
            "historicalDefensiveEventsWithObservedShifts":
                (shift_receipts or {}).get("matchedDefensiveShotEvents",0)}
