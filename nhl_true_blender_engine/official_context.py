"""Official NHL matchup, venue, schedule, rest and last-game context for G1.

Only observed schedule data is used. Calendar travel time, injury fatigue
and arbitrary road-distance metrics are not invented.
"""
from __future__ import annotations
import asyncio
from datetime import date,datetime,timezone
from .enrichment import ingest

async def collect_context(client,con,snapshot,slate_date,stage):
    start=int(slate_date[:4]) if int(slate_date[5:7])>=9 else int(slate_date[:4])-1
    season=f"{start}{start+1}"
    teams=sorted({t for g in snapshot.get("games",[]) for t in (g["away"],g["home"])})
    sem=asyncio.Semaphore(5)
    async def one(team):
        async with sem:
            try:
                response=await client.get(f"club-schedule-season/{team}/{season}")
                rows=response["data"].get("games")
                if not isinstance(rows,list):
                    raise ValueError("Missing games list")
                past=[r for r in rows if str(r.get("gameDate",""))<slate_date
                      and r.get("gameState") in ("OFF","FINAL")]
                past.sort(key=lambda x:str(x.get("gameDate","")))
                latest=past[-1] if past else None
                previous=latest.get("gameDate") if latest else None
                rest=(date.fromisoformat(slate_date)-date.fromisoformat(previous)).days-1 if previous else None
                if rest is not None and rest<0:
                    raise ValueError("Negative resting days from returned official schedule")
                return team,{"lastOfficialGameDate":previous,
                             "restDaysSinceLastFinal":rest,
                             "knownPreviousGameId":str(latest["id"]) if latest else None,
                             "sourceUrl":response["url"],"sourceObservedAt":response["observedAt"]},None
            except Exception as exc:
                return team,None,f"{type(exc).__name__}: {exc}"
    rows=await asyncio.gather(*(one(t) for t in teams))
    collected={t:info for t,info,err in rows if info}
    errors=[{"team":t,"error":err} for t,info,err in rows if err]
    count=0
    for game in snapshot.get("games",[]):
        away=collected.get(game["away"])
        home=collected.get(game["home"])
        # Venue is explicitly grounded by NHL official home/away designation.
        if not (away and home):
            errors.append({"gameId":game["id"],"error":"TEAM_SCHEDULE_NOT_FULLY_SOURCED"})
            continue
        payload={
            "gameId":str(game["id"]),"slateDate":slate_date,
            "venueHome":game["home"],"venueAway":game["away"],
            "awayRestDays":away["restDaysSinceLastFinal"],
            "homeRestDays":home["restDaysSinceLastFinal"],
            "awayPreviousGameId":away["knownPreviousGameId"],
            "homePreviousGameId":home["knownPreviousGameId"],
            "awayLastGameDate":away["lastOfficialGameDate"],
            "homeLastGameDate":home["lastOfficialGameDate"],
            "travelMiles":None,
            "travelDistanceNotInSource":True,
            "restIsCalendarDaysBetweenMinusOne":True,
            "sources":[away["sourceUrl"],home["sourceUrl"],game["officialSourceUrl"]],
            "dataScope":"OFFICIAL_SCHEDULE_NOT_TRAVEL_TRACKING",
        }
        ingest(con,{"evidence_id":f"nhl-context-{slate_date}-{stage}-{game['id']}",
            "slate_date":slate_date,"stage":stage,"game_id":str(game["id"]),
            "kind":"MATCH_CONTEXT","source_url":game["officialSourceUrl"],
            "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "payload":payload})
        count+=1
    return {"contextGames":count,"expectedGames":len(snapshot.get("games",[])),
            "teamScheduleSources":len(collected),"errors":errors,
            "noInventedTravel":True}
