"""Free official NHL shift-chart + pre-slate play-by-play defensive exposure.

Shift charts establish actual on-ice IDs during events in *historical games*.
Shot origin areas are derived from documented NHL PBP x/y and are approximations.
This is neither goal-mouth placement nor a confirmation of tonight's lines.
Missing/clashing clocks are excluded, never guessed or recast as a PASS.
"""
from __future__ import annotations
import asyncio
from collections import defaultdict
import httpx
from .official_defense_coverage import conservative_zone,detailed_shot_origin_zone

BASE="https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId%3D"
SHIFT_CODE=517

def period_seconds(raw):
    if not isinstance(raw,str):
        return None
    parts=raw.split(":")
    if len(parts)!=2 or not all(x.isdigit() for x in parts):
        return None
    minutes,seconds=map(int,parts)
    if seconds>=60 or minutes>30:
        return None
    return minutes*60+seconds

def parse_shifts(payload,game_id):
    if not isinstance(payload,dict) or not isinstance(payload.get("data"),list):
        raise ValueError("NHL shift feed missing official data list")
    rows=[];invalid=0
    for r in payload["data"]:
        if not isinstance(r,dict):invalid+=1;continue
        if str(r.get("gameId"))!=str(game_id):invalid+=1;continue
        if r.get("typeCode")!=SHIFT_CODE:continue
        start=period_seconds(r.get("startTime"))
        end=period_seconds(r.get("endTime"))
        team=r.get("teamId");pid=r.get("playerId");per=r.get("period")
        if not (type(team) is int and type(pid) is int and type(per) is int
                and per>0 and start is not None and end is not None
                and end>start and end-start<=1200):
            invalid+=1;continue
        rows.append({"gameId":str(game_id),"teamId":str(team),"playerId":str(pid),
                     "period":per,"startSeconds":start,"endSeconds":end})
    return rows,invalid

async def collect_shift_coverage(game_dates,events,game_meta,concurrency=5,*,source_cache=None):
    """Fetch only previously finalized games in the caller's dated sample."""
    sem=asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=16,follow_redirects=True,
                headers={"User-Agent":"NHLTrueBlender/1.0","Accept":"application/json"}) as client:
        async def one(gid):
            if source_cache is not None and str(gid) in source_cache:
                return source_cache[str(gid)]
            async with sem:
                url=BASE+str(gid)
                try:
                    resp=await client.get(url)
                    resp.raise_for_status()
                    rows,invalid=parse_shifts(resp.json(),gid)
                    result=(gid,url,rows,invalid,None)
                    if source_cache is not None and rows:
                        source_cache[str(gid)]=result
                    return result
                except (httpx.HTTPError,ValueError,KeyError) as exc:
                    return gid,url,[],0,f"{type(exc).__name__}: {exc}"
        fetched=await asyncio.gather(*(one(g) for g in game_dates))
    by_group=defaultdict(list)
    quality={}
    for gid,url,rows,invalid,err in fetched:
        quality[str(gid)]={"sourceUrl":url,"intervals":len(rows),
                           "invalidRows":invalid,"error":err}
        for r in rows:
            by_group[(r["gameId"],r["teamId"],r["period"])].append(r)
    # A defender must have genuinely observed players on the ice at the
    # event's exact period clock. Do not infer a shift from total TOI.
    by_defender=defaultdict(lambda:{"zoneEvents":defaultdict(int),
               "zoneSampleCounts":defaultdict(int),
               "sampleEvents":[],"gameIds":set(),"shiftSourceUrls":set(),
               "matchedEvents":0,"unmatchedEvents":0})
    matched=set()
    for e in events:
        if e.get("type") not in ("goal","shot-on-goal"):continue
        game_id=str(e.get("gameId"))
        game=game_meta.get(game_id)
        if not game:continue
        owner=str(e.get("ownerTeamId") or "")
        home=str(game.get("homeTeamId") or "")
        away=str(game.get("awayTeamId") or "")
        if owner not in (home,away) or not home or not away:continue
        defender=away if owner==home else home
        region=conservative_zone(e.get("x"),e.get("y"))
        detailed=detailed_shot_origin_zone(e.get("x"),e.get("y"))
        if not (region or detailed):continue
        period=e.get("period")
        clock=period_seconds(e.get("timeInPeriod"))
        event_id=str(e.get("eventId"))
        unique=(game_id,event_id)
        if unique in matched:continue
        matched.add(unique)
        result=by_defender[defender]
        if not (type(period) is int and period>0 and clock is not None):
            result["unmatchedEvents"]+=1
            continue
        shifts=by_group.get((game_id,defender,period),[])
        on_ice=sorted({x["playerId"] for x in shifts if
                       x["startSeconds"]<=clock<x["endSeconds"]})
        # An official shift chart with too few on-ice records cannot prove
        # defending players' availability for that event.
        if not 3<=len(on_ice)<=7:
            result["unmatchedEvents"]+=1
            continue
        result["matchedEvents"]+=1
        result["gameIds"].add(game_id)
        result["shiftSourceUrls"].add(BASE+game_id)
        zones=list(dict.fromkeys(z for z in (region,detailed) if z))
        for z in zones:
            result["zoneEvents"][z]+=1
            # Preserve source-backed defensive shifts for every observed
            # scoring area, including rare circle/point lanes late in the
            # pre-slate sample. The old first-180 global cap could discard an
            # entire real zone despite documented earlier/later PBP events.
            # Fixed cap of 16 official joined events PER area; no synthetic
            # event or substitute team/goalie share.
            if result["zoneSampleCounts"][z]<16:
                result["zoneSampleCounts"][z]+=1
                result["sampleEvents"].append({
                    "zone":z,"gameId":game_id,"eventId":event_id,
                    "period":period,"eventClock":e.get("timeInPeriod"),
                    "defendingOnIcePlayerIds":on_ice,
                    "officialPlayByPlayUrl":e.get("sourceUrl"),
                    "officialShiftChartUrl":BASE+game_id,
                    "historicalGameOnly":True,
                    "defensiveSkaterRolesNotInferred":True})
    normalized={}
    for team,row in by_defender.items():
        normalized[team]={
            "zoneEvents":dict(row["zoneEvents"]),
            "sampleEvents":row["sampleEvents"],
            "sourceGameIds":sorted(row["gameIds"]),
            "shiftSourceUrls":sorted(row["shiftSourceUrls"]),
            "matchedEvents":row["matchedEvents"],
            "unmatchedEvents":row["unmatchedEvents"],
        }
    return {"byDefendingTeamId":normalized,
            "chartedGames":sum(bool(x["intervals"]) for x in quality.values()),
            "attemptedGames":len(quality),
            "sampledOfficialIntervals":sum(x["intervals"] for x in quality.values()),
            "sourceFailures":[{"gameId":id,"error":x["error"] or
                ("EMPTY_OFFICIAL_SHIFT_CHART" if x["intervals"]==0 else "NO_VALID_INTERVALS")}
                for id,x in quality.items() if x["error"] or x["intervals"]==0][:30],
            "matchedDefensiveShotEvents":sum(x["matchedEvents"] for x in normalized.values()),
            "sourceScope":"HISTORICAL_OFFICIAL_NHL_SHIFT_INTERVALS_AND_PLAY_BY_PLAY",
            "doesNotConfirmTonightLines":True,
            "doesNotProveGloveBlockerOrFiveHole":True}
