"""G0 independent goalie-source fallback: official historical NHL game PBP.

Runs AFTER expected/confirmed goalie identities are independently attached.
Never manufactures glove/blocker/five-hole, never substitutes an opposing
team's goals, and never leaks same-day or post-puck results into pregame G0.

The NHL EDGE origin API can have no qualifying current-season areas for a
goalie. In that case fetch the GOALIE'S own game log and historical PBP
(with goalieInNetId identity) as an alternate, source-attributed observation.

Rink coordinate bins approximate shot ORIGINS; they are not identical to
NHL EDGE tracking polygons and never certify goal-mouth anatomy.
"""
from __future__ import annotations
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from statistics import median

from .enrichment import ingest
from .engine import all_goalie_branches
from .historical_shots import extract_events, ON_NET
from .official_defense_coverage import conservative_zone, detailed_shot_origin_zone

SOURCE="OFFICIAL_NHL_GOALIE_HISTORICAL_PBP_COORDINATE_PROXY_V1"
MIN_ORIGIN_SHOTS=20  # matching the 20-SOG observed denominator in NHL EDGE research
MIN_COMPARABLE_PEERS=4
MAX_LOW_PEER_RANK=0.35  # same percentile threshold as NHL EDGE, not a scorer weight


def pregame_log_games(payload, date, limit=16):
    """Only actual games strictly before the desired slate, by explicit date."""
    data=payload.get("data") or {}
    rows=data.get("gameLog")
    if not isinstance(rows,list):
        return []
    unique={}
    for g in rows:
        gid=g.get("gameId")
        played=g.get("gameDate") or g.get("date")
        if gid is None or not isinstance(played,str) or not played[:10]<date:
            continue
        # Exact calendar date safeguards against source response format shifts.
        try:
            datetime.strptime(played[:10],"%Y-%m-%d")
        except ValueError:
            continue
        unique[str(gid)]=played[:10]
    return sorted(unique.items(),key=lambda x:(x[1],x[0]),reverse=True)[:limit]


def _zone(event):
    """One conservative region per official goal/shot-on-goal event."""
    return (detailed_shot_origin_zone(event.get("x"),event.get("y"))
            or conservative_zone(event.get("x"),event.get("y")))


def summarize_goalie_origin_pbp(events):
    """Count only on-net official events with an exact goalieInNetId."""
    result=defaultdict(lambda:defaultdict(lambda:{
        "shotsAgainst":0,"goalsAgainst":0,"gameIds":set(),"sourceUrls":set()}))
    event_keys=set()
    for e in events:
        if e.get("type") not in ON_NET or not e.get("goalieId"):
            continue
        gid=str(e.get("goalieId"))
        game_id=str(e.get("gameId") or "")
        event_id=str(e.get("eventId") or "")
        key=(game_id,event_id)
        if not game_id or not event_id or key in event_keys:
            continue
        zone=_zone(e)
        if zone is None:continue
        event_keys.add(key)
        z=result[gid][zone]
        z["shotsAgainst"]+=1
        z["goalsAgainst"]+=int(e["type"]=="goal")
        z["gameIds"].add(game_id)
        if e.get("sourceUrl"):z["sourceUrls"].add(e["sourceUrl"])
    return result


def derive_independent_pbp_goalie_profile(goalie_id,zone_counts):
    """Derive peer-relative empirical shot-origin weaknesses, not certainty.

    Population is ONLY the fetched pre-slate official PBP goalie identities.
    A different goalie with a different sample is not silently assigned a
    *league* percentile. If peer comparison is insufficient, retain observed
    rows but mark this starter as NOT qualified for positive G0 weakness.
    """
    this=(zone_counts or {}).get(str(goalie_id))
    if not this:return None
    zones={};weak={};strong={};referenced=set();total=0
    for zone,z in sorted(this.items()):
        n=z["shotsAgainst"];goals=z["goalsAgainst"]
        total+=n
        comparable=[]
        for peer_id,rows in zone_counts.items():
            if peer_id==str(goalie_id) or zone not in rows:continue
            other=rows[zone]
            if other["shotsAgainst"]>=MIN_ORIGIN_SHOTS:
                comparable.append((peer_id,
                    (other["shotsAgainst"]-other["goalsAgainst"])/other["shotsAgainst"]))
        info={
            "shotsAgainst":n,"goalsAgainst":goals,
            "saves":n-goals,"savePctg":(n-goals)/n,
            "area":zone,"sampleGameIds":sorted(z["gameIds"]),
            "sourceUrls":sorted(z["sourceUrls"]),
            "peerGoalieIds":[pid for pid,pct in comparable],
            "peerGoaliesSampled":len(comparable),
            "originMap":"APPROXIMATE_NHL_PBP_RINK_COORDINATES",
            "anatomicalGoalMouthWeaknessVerified":False}
        referenced.update(z["sourceUrls"])
        if n>=MIN_ORIGIN_SHOTS and len(comparable)>=MIN_COMPARABLE_PEERS:
            saves=(n-goals)/n
            peer_rates=[p[1] for p in comparable]
            # PBP sample percentile is from the OBSERVED pooled peers, NOT
            # the NHL EDGE all-league savePctgPercentile. Match method only.
            rank=(sum(p<saves for p in peer_rates)+
                  .5*sum(p==saves for p in peer_rates))/len(peer_rates)
            info["samplePeerSavePctgPercentile"]=rank
            info["samplePeerMedianSavePctg"]=median(peer_rates)
            info["peerComparedSameOrigin"]=True
            if rank<=MAX_LOW_PEER_RANK and goals>0:
                weak[zone]=info
            elif rank>=1-MAX_LOW_PEER_RANK:
                strong[zone]=info
        zones[zone]=info
    if not referenced:return None
    return {
        "weakZones":weak,"strengthZones":strong,
        "observedAreas":zones,
        "sample":{"allZoneObservations":total,
                  "qualifiedAreaShots":sum(v["shotsAgainst"] for v in zones.values()
                      if "samplePeerSavePctgPercentile" in v),
                  "historicalGameIds":sorted({gid for x in this.values() for gid in x["gameIds"]})},
        "counterevidence":{
            "otherAreas":{z:x for z,x in zones.items() if z not in weak},
            "minShotsPerOrigin":MIN_ORIGIN_SHOTS,
            "peerMinDistinctGoalies":MIN_COMPARABLE_PEERS,
            "observedPeerSaveRankThreshold":MAX_LOW_PEER_RANK,
            "noAnatomicalClaims":True},
        "fullySourceComparedAreas":sum("samplePeerSavePctgPercentile" in x
                                        for x in zones.values()),
        "sourceType":SOURCE,"sourceClass":"INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY",
        "anatomicalWeaknessCertified":False,
        "weaknessMeaning":"historical observed shots allowed from approximate rink origin vs sampled peer goalies",
        "historicalPbpSources":sorted(referenced),
        "doesNotUseToday'sGame":True,
    }


async def collect_goalie_pbp_fallback(client,con,snapshot,date,stage,max_games=16,
                                      request_concurrency=5):
    """Fetch exact starter identities and source-linked past NHL goalie games.

    Only goalies without a FULLY sourced independent measured profile require
    another fetch. PBP from each requested game also yields independent peer
    goalie shot rates. Do not overwrite an NHL EDGE source that already
    certified a relative weakness or a complete source review.
    """
    active={}
    source_failures=[]
    for game in snapshot.get("games",[]):
        for team,branches in all_goalie_branches(game,stage).items():
            for branch in branches:
                data=branch.get("data") or {}
                pid=data.get("goalieId")
                if not pid:continue
                good=(data.get("sourceClass")=="DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"
                      and isinstance(data.get("observedAreas"),dict)
                      and data.get("sample",{}).get("allZoneObservations",0)>=MIN_ORIGIN_SHOTS)
                if good or data.get("sourceClass")=="INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY":
                    continue
                active[str(pid)]=None
    if not active:
        return {"status":"ALL_GOALIE_PROFILES_ALREADY_MEASURED",
                "goaliesNeedingPbpResearch":0,
                "sourceType":SOURCE,"fallbackProfiles":0,"sourceFailures":[]}
    season_start=int(date[:4]) if int(date[5:7])>=9 else int(date[:4])-1
    seasons=[f"{season_start}{season_start+1}",f"{season_start-1}{season_start}"]
    sem=asyncio.Semaphore(request_concurrency)
    async def get_log(pid,season):
        async with sem:
            try:
                data=await client.game_log(pid,season)
                return pid,season,data,None
            except Exception as exc:
                return pid,season,None,type(exc).__name__+": "+str(exc)[:190]
    logs=await asyncio.gather(*(get_log(pid,season) for pid in active for season in seasons))
    games={}
    for pid,season,payload,error in logs:
        if error:
            source_failures.append({"goalieId":pid,"endpoint":"game-log",
                                    "season":season,"reason":error})
            continue
        for gid,played in pregame_log_games(payload,date,max_games):
            games.setdefault(gid,played)
    # Need to ensure no one goalie dominates the pooled sample just due to
    # twice as many fetched games; collect one deduplicated URL per game.
    async def get_game(gid,played):
        async with sem:
            try:
                raw=await client.play_by_play(gid)
                return gid,extract_events(raw,gid,played),None
            except Exception as exc:
                return gid,[],type(exc).__name__+": "+str(exc)[:180]
    outcomes=await asyncio.gather(*(get_game(gid,played) for gid,played in games.items()))
    events=[]
    for gid,shots,error in outcomes:
        if error:
            source_failures.append({"gameId":gid,"endpoint":"play-by-play","reason":error})
            continue
        events.extend(shots)
    stats=summarize_goalie_origin_pbp(events)
    saved=0;fully_compared=0;unresolved=[]
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for game in snapshot.get("games",[]):
        for team,branches in all_goalie_branches(game,stage).items():
            for branch in branches:
                pid=str(branch["data"].get("goalieId") or "")
                if pid not in active:continue
                derived=derive_independent_pbp_goalie_profile(pid,stats)
                if not derived:
                    unresolved.append({"gameId":str(game["id"]),"goalieId":pid,
                           "reason":"No individually identified NHL goalie saves/goals with historical rink coordinates"})
                    continue
                derived.update({"team":team,"goalieId":pid,"status":branch["data"]["status"],
                    "starterSourceUrl":branch["sourceUrl"],
                    "historicalSampleAsOf":date,
                    "sourceGameIds":derived["sample"]["historicalGameIds"]})
                if not derived["fullySourceComparedAreas"]:
                    unresolved.append({"gameId":str(game["id"]),"goalieId":pid,
                         "reason":"Official PBP exists, but goalie-versus-peer area evidence lacks denominator or peer comparator"})
                else:
                    fully_compared+=1
                urls=derived["historicalPbpSources"]
                digest=hashlib.sha256(json.dumps(derived,sort_keys=True,
                          separators=(",",":")).encode()).hexdigest()[:14]
                ingest(con,{"evidence_id":f"nhl-pbp-goalie-{date}-{stage}-{game['id']}-{pid}-{digest}",
                    "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                    "kind":"GOALIE_PROFILE",
                    "source_url":urls[0],
                    "observed_at":now,"payload":derived})
                saved+=1
    return {
        "status":"OFFICIAL_PBP_FALLBACK_COLLECTED",
        "sourceType":SOURCE,
        "goaliesNeedingPbpResearch":len(active),
        "historicalNhlGamesFetched":sum(err is None for gid,events,err in outcomes),
        "historicalGoalieIdentityEvents":sum(x.get("goalieId") is not None
                                             and x.get("type") in ON_NET for x in events),
        "fallbackProfiles":saved,
        "goaliesWithPeerComparedOrigins":fully_compared,
        "unresolved":unresolved[:30],
        "sourceFailures":source_failures[:30],
        "historicalOnly":True,
        "anatomicalClaimCertified":False,
    }
