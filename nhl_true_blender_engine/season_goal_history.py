"""Official NHL full current-season player game logs for historical goal credit.

This source supplements, never replaces, the eight recent-team-game PBP
samples. A goal credited on an earlier season date is real historical scorer
evidence; it is never proof of scoring tonight or a fabricated event ID.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .enrichment import ingest

ET=ZoneInfo("America/New_York")
SOURCE_TYPE="NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG"

def decode_dated_goals(payload, player_id, slate_date):
    """Accept only individually dated past-season official goal-credit rows."""
    if not isinstance(payload,dict) or not isinstance(payload.get("gameLog"),list):
        return None
    reviewed=[]; invalid=0
    seen=set()
    for row in payload["gameLog"]:
        if not isinstance(row,dict):
            invalid+=1;continue
        date=row.get("gameDate")
        gid=row.get("gameId")
        goals=row.get("goals")
        shots=row.get("shots")
        if (not isinstance(date,str) or len(date)!=10 or
                not date[:4].isdigit() or
                not isinstance(gid,(str,int)) or not str(gid).isdigit() or
                type(goals) is not int or goals<0 or
                type(shots) is not int or shots<0 or
                goals>shots or str(gid) in seen):
            invalid+=1;continue
        seen.add(str(gid))
        if date>=slate_date:
            # Neither same-day final games nor future games may enter this
            # pre-slate scorer selection.
            continue
        reviewed.append({"gameId":str(gid),"date":date,
                         "goals":goals,"shotsOnGoal":shots})
    # A malformed source is not a successful negative season-goals claim.
    if invalid or not reviewed:
        return None
    reviewed.sort(key=lambda x:(x["date"],x["gameId"]),reverse=True)
    return {"playerId":str(player_id),
            "sourceType":SOURCE_TYPE,
            "scope":"OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE",
            "officialPastSeasonGoals":sum(x["goals"] for x in reviewed),
            "goalScoringGames":[x for x in reviewed if x["goals"]>0],
            "actualAppearances":len(reviewed),
            "datedGames":reviewed,
            "sameSlateDateExcluded":True,
            "neverClaimedTonightGoal":True,
            "noSyntheticGoalEventIds":True,
            "notFullPbpEventReconciliation":True}

async def collect_season_goal_history(client,con,snapshot,date,stage,concurrency=6):
    """Research every roster skater, not only favorite scorers or G0 survivors."""
    if date!=datetime.now(ET).date().isoformat():
        return {"status":"NOT_LIVE_AS_OF_SLATE_DATE","sourcedSkaters":0,
                "avoidsFutureStatLeakage":True}
    start=int(date[:4]) if int(date[5:7])>=9 else int(date[:4])-1
    season=f"{start}{start+1}"
    players={}
    for game in snapshot.get("games",[]):
        for team in (game["away"],game["home"]):
            roster=(game.get("rosters",{}).get(team) or {}).get("data") or {}
            for player in roster.get("players",[]):
                if str(player.get("id","")).isdigit():
                    pid=str(player["id"])
                    players.setdefault(pid,[]).append(str(game["id"]))
    sem=asyncio.Semaphore(concurrency)
    async def one(pid):
        async with sem:
            try:
                raw=await client.game_log(pid,season)
                proof=decode_dated_goals(raw["data"],pid,date)
                return pid,raw,proof,None
            except Exception as exc:
                return pid,None,None,f"{type(exc).__name__}: {exc}"
    results=await asyncio.gather(*(one(pid) for pid in players))
    sourced=0;scorers=0;errors=[]
    for pid,raw,proof,error in results:
        if not proof:
            errors.append({"playerId":pid,"reason":error or "SOURCE_MISSING_OR_INCOMPLETE_DATED_GAMES"})
            continue
        proof["officialSourceUrl"]=raw["url"]
        digest=hashlib.sha256(json.dumps(
            proof,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:20]
        for gid in players[pid]:
            ingest(con,{"evidence_id":f"nhl-season-log-{date}-{stage}-{gid}-{pid}-{digest}",
                "slate_date":date,"stage":stage,"game_id":gid,"player_id":pid,
                "kind":"PLAYER_SEASON_HISTORY","source_url":raw["url"],
                "observed_at":raw["observedAt"],"payload":proof})
        sourced+=1
        scorers+=int(proof["officialPastSeasonGoals"]>0)
    return {"status":"SOURCE_REVIEW_COMPLETED","playersQueried":len(players),
            "sourcedSkaters":sourced,"playersWithCreditedSeasonGoals":scorers,
            "unavailable":len(errors),"examples":errors[:20],
            "season":season,"scope":SOURCE_TYPE,
            "avoidsFutureStatLeakage":True,"noGoalEventsInvented":True}
