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


def derive_independent_pbp_goalie_profile(goalie_id,zone_counts,peer_counts=None):
    """Derive peer-relative empirical shot-origin weaknesses, not certainty.

    Population is ONLY the fetched pre-slate official PBP goalie identities.
    A different goalie with a different sample is not silently assigned a
    *league* percentile. If peer comparison is insufficient, retain observed
    rows but mark this starter as NOT qualified for positive G0 weakness.
    """
    this=(zone_counts or {}).get(str(goalie_id))
    if not this:return None
    # When independent league-wide pre-slate NHL PBP exists, only THAT
    # stable cohort may define percentiles. Current projected goalie
    # identities can change without changing a single historical save:
    # adding/removing them from the denominator is an artificial G0 flip.
    reference=(zone_counts if peer_counts is None else peer_counts)
    zones={};weak={};strong={};referenced=set();total=0
    for zone,z in sorted(this.items()):
        n=z["shotsAgainst"];goals=z["goalsAgainst"]
        total+=n
        comparable=[]
        for peer_id,rows in reference.items():
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


def needs_independent_pbp(data):
    """A measured total without a qualified peer/source review is not G0 proof.

    A goalie can have a nonempty NHL EDGE shot-location response containing
    only unqualified areas; the previous predicate treated any 20 shots as a
    completed goalie review and never fetched the official PBP fallback.
    """
    if not isinstance(data,dict):
        return True
    observations=data.get("observedAreas")
    sample=data.get("sample") or {}
    if (data.get("sourceClass")=="DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"
        and data.get("sourceReviewed") is True
        and isinstance(observations,dict)
        and type(sample.get("allZoneObservations")) is int
        and sample["allZoneObservations"]>=MIN_ORIGIN_SHOTS):
        return False
    if (data.get("sourceClass")=="INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY"
        and type(data.get("fullySourceComparedAreas")) is int
        and data["fullySourceComparedAreas"]>0):
        return False
    return True


def combine_official_pregame_goalie_peers(target_events, league_events, slate_date):
    """Merge independently collected NHL PBP without counting a game twice.

    The target's own separately fetched goalie-identified shots remain the
    basis of the goalie profile. The league-wide historical games only supply
    additional *actual* opposing goalie identities for same-area comparison.
    Unknown, anonymous, same-day and post-slate events never enter the cohort.
    This is rink shot ORIGIN data, not glove/blocker/five-hole data.
    """
    target_games={str(e.get("gameId")) for e in target_events
                  if e.get("gameId") is not None}
    seen={(str(e.get("gameId")),str(e.get("eventId"))) for e in target_events}
    peers=[]
    added_games=set()
    for e in league_events or []:
        if not isinstance(e,dict):
            continue
        gid=str(e.get("gameId") or "")
        eventid=str(e.get("eventId") or "")
        played=e.get("date")
        url=e.get("sourceUrl")
        if (not gid or not eventid or gid in target_games
            or not isinstance(played,str) or len(played)!=10
            or played>=slate_date
            or e.get("type") not in ON_NET
            or str(e.get("goalieId") or "").lower() in ("","none","null","0")
            or not isinstance(url,str)
            or not url.startswith("https://api-web.nhle.com/")):
            continue
        key=(gid,eventid)
        if key in seen:
            continue
        seen.add(key)
        added_games.add(gid)
        peers.append(e)
    return list(target_events)+peers, len(added_games)


async def collect_goalie_pbp_fallback(client,con,snapshot,date,stage,max_games=16,
                                      request_concurrency=5,league_peer_events=None):
    """Fetch exact starter identities and source-linked past NHL goalie games.

    Only goalies without a FULLY sourced independent measured profile require
    another fetch. PBP from each requested game also yields independent peer
    goalie shot rates. Do not overwrite an NHL EDGE source that already
    certified a relative weakness or a complete source review.
    """
    active={}
    eligible_peers={}
    source_failures=[]
    for game in snapshot.get("games",[]):
        for team,branches in all_goalie_branches(game,stage).items():
            for branch in branches:
                data=branch.get("data") or {}
                pid=data.get("goalieId")
                if not pid:continue
                # The historical goalie itself cannot serve as its own peer.
                # Other independently identified slate goalies are a
                # legitimate SAME-RINK-ZONE historical peer cohort. Collect
                # their dated pre-slate PBP games but do NOT change their
                # accepted EDGE profiles, starter status, or the G0 decision.
                eligible_peers.setdefault(str(pid),set()).add(team)
                if needs_independent_pbp(data):
                    active.setdefault(str(pid),set()).add(team)
    if not eligible_peers:
        return {"status":"NO_SOURCE_IDENTIFIED_SLATE_GOALIES",
                "goaliesNeedingPbpResearch":0,
                "sourceType":SOURCE,"fallbackProfiles":0,"sourceFailures":[]}
    # Even when every goalie has a usable independent NHL EDGE profile,
    # G0 can fail because its STARTER branches or measured areas cannot be
    # ranked in the same comparator family. A shared dated NHL goalie PBP
    # peer population is therefore collected for BOTH sides regardless of
    # whether an EDGE profile is already present. These are supplementary
    # G0 comparisons only; no EDGE receipts are replaced or falsely
    # promoted to confirmed. The prior early-return made the entire
    # same-cohort repair unreachable on repeat projected runs.
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
    # A single reserve goalie's 16 historical games usually contains only
    # ONE full goalie sample; opposing goalies seen once each often fail the
    # 20-shot SAME-ORIGIN peer denominator. Previously G0 falsely reported
    # "no peers" even though all remaining slate goalies had NHL game logs.
    # Collect the same pre-slate history for each candidate peer first.
    logs=await asyncio.gather(*(get_log(pid,season)
                                for pid in eligible_peers for season in seasons))
    games={}
    goalies_with_history=set()
    for pid,season,payload,error in logs:
        if error:
            source_failures.append({"goalieId":pid,"endpoint":"game-log",
                                    "season":season,"reason":error})
            continue
        for gid,played in pregame_log_games(payload,date,max_games):
            games.setdefault(gid,played)
            goalies_with_history.add(pid)
    # A newly called-up / traded goalie may lack a goalie game-log response.
    # Query the club's own OFFICIAL pre-slate season schedule as a second
    # discovery route. This does not assume the goalie played for the club:
    # each shot is attributed only by goalieInNetId in the actual game PBP.
    missing=[(pid,team,season) for pid,teams in active.items()
             if pid not in goalies_with_history
             for team in teams for season in seasons]
    async def club_schedule(pid,team,season):
        async with sem:
            try:
                raw=await client.get(f"club-schedule-season/{team}/{season}")
                return pid,team,season,raw,None
            except Exception as exc:
                return pid,team,season,None,type(exc).__name__+": "+str(exc)[:190]
    fallback_schedules=await asyncio.gather(*(club_schedule(*entry)
                                             for entry in missing))
    recovered_schedule_games=0
    for pid,team,season,payload,error in fallback_schedules:
        if error:
            source_failures.append({"goalieId":pid,"team":team,
                 "endpoint":"club-schedule-season","season":season,"reason":error})
            continue
        # This is a discovery set, never a scorer or starter confirmation.
        # The goalie identity itself MUST appear in goalieInNetId PBP.
        eligible=[]
        for row in (payload.get("data") or {}).get("games",[]):
            gid=row.get("id")
            played=row.get("gameDate")
            if gid is None or not isinstance(played,str) or played[:10]>=date:
                continue
            if row.get("gameState") not in ("OFF","FINAL"):
                continue
            eligible.append((str(gid),played[:10]))
        eligible.sort(key=lambda item:item[1],reverse=True)
        for gid,played in eligible[:max_games]:
            if gid not in games:
                games[gid]=played
                recovered_schedule_games+=1
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
    # These records were already fetched, dated and identified by the
    # independent league-wide G9 official PBP collector. Reuse the real
    # peer goalies here instead of interpreting a one-goalie sample as
    # absence of peer data or fetching the same public games again.
    merged,extra_peer_games=combine_official_pregame_goalie_peers(
        events,league_peer_events,date)
    target_only=summarize_goalie_origin_pbp(events)
    stats=summarize_goalie_origin_pbp(merged)
    # A goalie pulled from today's PROJECTED group must NOT mutate the
    # empirical denominator used for some OTHER goalie's G0 direction.
    # league_peer_events are dated official league-wide prior-game PBP
    # collected independently of today's starter identities.
    stable_peer_events,_=combine_official_pregame_goalie_peers(
        [],league_peer_events,date)
    fixed_cohort=bool(stable_peer_events)
    reference_stats=(summarize_goalie_origin_pbp(stable_peer_events)
                     if fixed_cohort else stats)
    own_samples=target_only if fixed_cohort else stats
    # Hash all independent source observations, including actual goal type,
    # so a new official correction gets a new auditable cohort ID. Never
    # hash today's projected list or our targeted goalie fetching order.
    reference_signature=(
       sorted((str(x['gameId']),str(x['eventId']),
               str(x['goalieId']),str(x['type']),str(x['date']))
              for x in stable_peer_events)
       if fixed_cohort else
       [('DYNAMIC_FALLBACK',str(gid)) for gid in sorted(games)])
    saved=0;fully_compared=0;unresolved=[];cohort_profiles=0
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    population=hashlib.sha256(json.dumps({
        "slate":date,"sampleEvents":reference_signature,
        "sourceScope":SOURCE,
        "referenceIndependentOfProjectedGoalies":fixed_cohort},
        sort_keys=True).encode()).hexdigest()[:20]
    for game in snapshot.get("games",[]):
        for team,branches in all_goalie_branches(game,stage).items():
            for branch in branches:
                pid=str(branch["data"].get("goalieId") or "")
                if pid not in eligible_peers:continue
                # A peer goalie can become a COMPARABLE goalie without
                # replacing its existing NHL EDGE profile. Require that
                # goalie's OWN PBP game-log events, never roster inference.
                derived=(derive_independent_pbp_goalie_profile(
                    pid,own_samples,
                    peer_counts=reference_stats if fixed_cohort else None)
                    if pid in target_only else None)
                if derived and derived["fullySourceComparedAreas"]>0:
                    peer={**derived,"team":team,"goalieId":pid,
                          "status":branch["data"]["status"],
                          "samplePeerPopulationId":population,
                          "historicalSampleAsOf":date,
                          "peerSampleNeverLeagueEDGEPercentile":True,
                          "sourceGameIds":derived["sample"]["historicalGameIds"]}
                    digest=hashlib.sha256(json.dumps(
                        peer,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:14]
                    urls=derived["historicalPbpSources"]
                    ingest(con,{"evidence_id":f"nhl-pbp-peer-{date}-{stage}-{game['id']}-{pid}-{digest}",
                        "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                        "kind":"GOALIE_PBP_PEER_CONTEXT",
                        "source_url":urls[0],"observed_at":now,"payload":peer})
                    cohort_profiles+=1
                if pid not in active:continue
                if not derived:
                    unresolved.append({"gameId":str(game["id"]),"goalieId":pid,
                           "reason":"No individually identified NHL goalie saves/goals with historical rink coordinates"})
                    continue
                derived.update({"team":team,"goalieId":pid,"status":branch["data"]["status"],
                    "starterSourceUrl":branch["sourceUrl"],
                    "historicalSampleAsOf":date,
                    # Shared independent pre-slate peer cohort is required for
                    # later G10.5/G16 comparison. Never treat a locally
                    # assembled, starter-dependent cohort as league-wide.
                    "samplePeerPopulationId":population,
                    "samplePeerPopulationStable":fixed_cohort,
                    "peerSampleNeverLeagueEDGEPercentile":True,
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
        "independentlyIdentifiedSlateGoaliePeers":len(eligible_peers),
        "distinctPreSlateNhlGamesCompared":len(games)+extra_peer_games,
        "addedIndependentLeaguePeerGames":extra_peer_games,
        "distinctPeerGoaliesWithOnNetEvents":len(stats),
        "samplePeersNotFullLeaguePercentile":True,
        "historicalNhlGamesFetched":sum(err is None for gid,events,err in outcomes),
        "goaliesWithOfficialPersonalHistory":len(goalies_with_history),
        "clubScheduleGamesRecovered":recovered_schedule_games,
        "clubScheduleNeverImpliesGoaliePlayed":True,
        "historicalGoalieIdentityEvents":sum(x.get("goalieId") is not None
                                             and x.get("type") in ON_NET for x in events),
        "fallbackProfiles":saved,
        "goaliesWithPeerComparedOrigins":fully_compared,
        "independentSameCohortProfiles":cohort_profiles,
        "independentSameCohortPopulationId":population,
        "cohortIndependentOfProjectedStarterRoster":fixed_cohort,
        "cohortSource":"PRE_SLATE_LEAGUE_WIDE_NHL_PBP" if fixed_cohort else "FETCHED_GOALIE_GAME_LOG_PEERS",
        "cohortComparatorNotMixedWithEDGE":True,
        "unresolved":unresolved[:30],
        "sourceFailures":source_failures[:30],
        "historicalOnly":True,
        "anatomicalClaimCertified":False,
    }
