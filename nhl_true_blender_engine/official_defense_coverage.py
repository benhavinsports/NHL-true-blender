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
MIN_DEFENSE_SOURCE_SHOTS=70
MIN_ZONE_SHOTS=8

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
    by_team=defaultdict(lambda:{"totalShots":0,"bins":defaultdict(int),"gameIds":set(),
                            "sourceUrls":set()})
    seen=set()
    for e in events:
        if e.get("type") not in ("goal","shot-on-goal"):
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
        if eid in seen:continue
        seen.add(eid)
        defender=away if owner==home else home
        row=by_team[defender]
        row["totalShots"]+=1
        # Keep original conservative broad bins, but also measure the
        # separately sourced EDGE-compatible circle/point-lane proxies.
        # Without these areas G9 could never review a documented L/R Circle
        # goalie vulnerability; it wrongly treated "not mapped" as "not weak".
        region=conservative_zone(e.get("x"),e.get("y"))
        detail=detailed_shot_origin_zone(e.get("x"),e.get("y"))
        if region:row["bins"][region]+=1
        if detail:row["bins"][detail]+=1
        row["gameIds"].add(e["gameId"])
        if e.get("sourceUrl"):row["sourceUrls"].add(e["sourceUrl"])
    return by_team

def make_coverage(con,snapshot,date,stage,events,game_meta):
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
    comparisons={}
    for z in ("Low Slot","High Slot","Point","L Circle","R Circle",
              "L Point","R Point","Center Point"):
        peers=[row["bins"].get(z,0)/row["totalShots"]
               for row in by_team.values()
               if row["totalShots"]>=MIN_DEFENSE_SOURCE_SHOTS]
        comparisons[z]=median(peers) if len(peers)>=6 else None
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    count=0;fail=[]
    for game in snapshot.get("games",[]):
        for attacker,defender in ((game["away"],game["home"]),(game["home"],game["away"])):
            pid=abbr_to_id.get(defender)
            row=by_team.get(pid) if pid else None
            if not row or row["totalShots"]<MIN_DEFENSE_SOURCE_SHOTS:
                fail.append({"gameId":str(game["id"]),"defender":defender,
                            "reason":"Not enough independently sourced historical shots against"})
                continue
            green={};red={};detail={}
            for z in comparisons:
                med=comparisons[z]
                if med is None:continue
                n=row["bins"].get(z,0)
                share=n/row["totalShots"]
                info={"shotsAgainst":n,"allOnNetShotsAgainst":row["totalShots"],
                      "share":share,"peerMedianShare":med,
                      "gameCount":len(row["gameIds"]),
                      "classification":BIN_SPEC}
                detail[z]=info
                if n>=MIN_ZONE_SHOTS and share>med:
                    green[z]=info
                elif n>=MIN_ZONE_SHOTS and share<med:
                    red[z]=info
            if not detail:
                fail.append({"gameId":str(game["id"]),"defender":defender,
                            "reason":"No defensible peer comparison"})
                continue
            urls=sorted(row["sourceUrls"])
            payload={"attackingTeam":attacker,"defendingTeam":defender,
                "greenWeakZones":list(green),"redStrongZones":list(red),
                "zoneConcessions":detail,
                "comparison":"RECENT_OPPONENT_SHOT_ORIGIN_SHARES_AGAINST_PEER_MEDIAN",
                "method":BIN_SPEC,
                "derivedCirclePointAreas":True,
                "derivedAreasNotExactNhlEdgeTrackingPolygons":True,
                "coordinateSystem":"NHL_PBP_ARENA_FRAME_ORIENTED_TO_ATTACKING_NET",
                "noGloveBlockerFiveHoleInterpretation":True,
                "comparisonSampleTeams":sum(bool(q) for q in by_team.values()),
                "trackedGameIds":sorted(row["gameIds"]),
                "sourceUrls":urls,
                "inferredLaneNotExactNhlEdgePolygon":True,
                "strengthsAndWeaknessesAreTeamShot_SHARE_NotGoalieSavePct":True,
                "unobservedAreasNotAssignedGreen":True}
            if urls:
                # The 8-game evidence window and the labelled area inference
                # can change between confirmed refreshes. Each distinct
                # measured payload is a NEW immutable proof, never an update
                # to the previously saved G9 source claim.
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
            "peerMedianZoneShares":comparisons,
            "failedSources":fail[:15],
            "sourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
            "zonesAreConservativeDerivedRinkAreas":True}
