"""Official NHL matchup, venue, schedule, rest and last-game context for G1.

Only observed schedule data is used. Calendar travel time, injury fatigue
and arbitrary road-distance metrics are not invented.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
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
                upcoming=[r for r in rows if r.get('gameState') in ('FUT','PRE')
                          and r.get('startTimeUTC') and
                          datetime.fromisoformat(r['startTimeUTC'].replace('Z','+00:00'))>
                              datetime.now(timezone.utc)]
                upcoming.sort(key=lambda r:r['startTimeUTC'])
                next_game=upcoming[0] if upcoming else None
                return team,{"lastOfficialGameDate":previous,
                             "nextScheduledGameId":str(next_game['id']) if next_game else None,
                             "restDaysSinceLastFinal":rest,
                             "knownPreviousGameId":str(latest["id"]) if latest else None,
                             "lastGameStartUTC":latest.get("startTimeUTC") if latest else None,
                             "lastGameVenue":latest.get("venue") if latest else None,
                             "lastGameHomeTeam":(latest.get("homeTeam") or {}).get("abbrev") if latest else None,
                             "recentScheduleSequence":[{
                                 "gameId":str(row["id"]),"date":row.get("gameDate"),
                                 "startUTC":row.get("startTimeUTC"),
                                 "homeTeam":(row.get("homeTeam") or {}).get("abbrev"),
                                 "awayTeam":(row.get("awayTeam") or {}).get("abbrev"),
                                 "venue":row.get("venue"),
                                 "sourceUrl":response["url"],
                                 "observedAt":response["observedAt"]}
                                 for row in past[-3:]],
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
            "venue":game.get("venue"),"startUTC":game.get("startUTC"),
            "awayRestDays":away["restDaysSinceLastFinal"],
            "homeRestDays":home["restDaysSinceLastFinal"],
            "awayPreviousGameId":away["knownPreviousGameId"],
            "homePreviousGameId":home["knownPreviousGameId"],
            "awayLastGameDate":away["lastOfficialGameDate"],
            "homeLastGameDate":home["lastOfficialGameDate"],
            "nextScheduledGameIds":{
                game['away']:away['nextScheduledGameId'],
                game['home']:home['nextScheduledGameId']},
            "awayBackToBack":away["restDaysSinceLastFinal"]==0 if away["restDaysSinceLastFinal"] is not None else None,
            "homeBackToBack":home["restDaysSinceLastFinal"]==0 if home["restDaysSinceLastFinal"] is not None else None,
            "teamScheduleSequences":{
                game["away"]:away["recentScheduleSequence"],
                game["home"]:home["recentScheduleSequence"]},
            "scheduledVenueTransitions":{
                game["away"]:{"previousVenue":away["lastGameVenue"],
                    "previousHomeTeam":away["lastGameHomeTeam"],
                    "previousStartUTC":away["lastGameStartUTC"],
                    "currentVenue":game.get("venue"),"currentHomeTeam":game["home"]},
                game["home"]:{"previousVenue":home["lastGameVenue"],
                    "previousHomeTeam":home["lastGameHomeTeam"],
                    "previousStartUTC":home["lastGameStartUTC"],
                    "currentVenue":game.get("venue"),"currentHomeTeam":game["home"]}},
            "scheduleSequenceIsNotObservedFlightOrFatigue":True,
            "travelMiles":None,
            "travelDistanceNotInSource":True,
            "restIsCalendarDaysBetweenMinusOne":True,
            "sources":[away["sourceUrl"],home["sourceUrl"],game["officialSourceUrl"]],
            "dataScope":"OFFICIAL_SCHEDULE_NOT_TRAVEL_TRACKING",
        }
        digest=hashlib.sha256(json.dumps(
            payload,sort_keys=True,separators=(",",":")).encode("utf-8")
            ).hexdigest()[:20]
        ingest(con,{"evidence_id":f"nhl-context-{slate_date}-{stage}-{game['id']}-{digest}",
            "slate_date":slate_date,"stage":stage,"game_id":str(game["id"]),
            "kind":"MATCH_CONTEXT","source_url":game["officialSourceUrl"],
            "observed_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "payload":payload})
        count+=1
    return {"contextGames":count,"expectedGames":len(snapshot.get("games",[])),
            "teamScheduleSources":len(collected),"errors":errors,
            "noInventedTravel":True}

