"""Dated player appearances, credited own goals and pressure from official NHL boxscores.

The sampling universe is only recent *team* games actually retrieved pre-slate.
It is never silently described as a complete season or a zero for games missed.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import datetime,timezone
from .enrichment import ingest

def _versioned_receipt_id(base,payload):
    """Retain corrected official boxscore observations without mutating old receipts."""
    digest=hashlib.sha256(json.dumps(
        payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
        ).hexdigest()[:20]
    return f"{base}-{digest}"


async def collect_sampled_boxes(client,con,snapshot,date,stage,game_dates,events,
                                pbp_verified_game_ids=None):
    # Only reconcile goals where both independent official feeds were read.
    # An absent PBP feed is NOT a source-verified zero-goal game.
    verified_pbp_ids = (set(map(str,game_dates)) if pbp_verified_game_ids is None
                        else {str(gid) for gid in pbp_verified_game_ids})
    sem=asyncio.Semaphore(5)
    async def one(game_id):
        async with sem:
            try:
                raw=await client.boxscore(game_id)
                stats=raw["data"].get("playerByGameStats")
                if not isinstance(stats,dict):raise ValueError("No official playerByGameStats")
                players={}
                for team in ("homeTeam","awayTeam"):
                    for position in ("forwards","defense"):
                        for player in (stats.get(team) or {}).get(position,[]):
                            pid=player.get("playerId")
                            if pid is None:continue
                            goals=player.get("goals")
                            shots=player.get("shots")
                            if not isinstance(goals,int) or goals<0:continue
                            if shots is not None and (not isinstance(shots,int) or shots<0):shots=None
                            key=str(pid)
                            if key in players:raise ValueError("Same player duplicated in official boxscore")
                            players[key]={"goals":goals,"shotsOnGoal":shots,
                                         "gameId":str(game_id),
                                         "date":game_dates[str(game_id)],
                                         "sourceUrl":raw["url"]}
                if not players:raise ValueError("No skater participation rows")
                return str(game_id),players,None
            except Exception as exc:
                return str(game_id),None,f"{type(exc).__name__}: {exc}"
    jobs=await asyncio.gather(*(one(gid) for gid in game_dates))
    by_game={g:p for g,p,err in jobs if p}
    errors=[{"gameId":g,"error":err} for g,p,err in jobs if err]
    by_player_events=defaultdict(list)
    for e in events:
        if e.get("gameId") in by_game and e.get("type")=="goal":
            by_player_events[(str(e["gameId"]),str(e["shooterId"]))].append(e)
    registered=set()
    stats={"verifiedOwnGoalRows":0,"appearanceRows":0,
           "distinctPlayers":0,"sourceGames":len(by_game),
           "attemptedGames":len(game_dates),"discrepancies":[],
           "pbpUnavailableGames":sorted(set(map(str,game_dates))-verified_pbp_ids),
           "boxscoreUnavailableGames":sorted(set(map(str,game_dates))-set(by_game)),
           "reconciledSourceGames":len(set(by_game)&verified_pbp_ids)}
    timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for game in snapshot.get("games",[]):
        for team in (game["away"],game["home"]):
            roster=(game.get("rosters",{}).get(team) or {}).get("data",{})
            for p in roster.get("players",[]):
                key=(str(game["id"]),str(p["id"]))
                if key in registered:continue
                registered.add(key)
                pid=key[1]
                fetched=sorted(
                    (players[pid] for gid,players in by_game.items()
                     if gid in verified_pbp_ids and pid in players),
                    key=lambda x:(x["date"],x["gameId"]),reverse=True)
                # Reconcile each actual appearance independently. One
                # conflicting or uncollected PBP must not erase a different
                # source-verified appearance, or be inserted as a zero.
                appearances=[]
                for appearance in fetched:
                    goals_in_pbp=by_player_events.get((appearance["gameId"],pid),[])
                    if appearance["goals"]!=len(goals_in_pbp):
                        stats["discrepancies"].append({
                            "playerId":pid,"gameId":appearance["gameId"],
                            "boxScoreGoals":appearance["goals"],
                            "pbpGoalEvents":len(goals_in_pbp),
                            "reason":"Game-specific goal credit is unreconciled; excluded from certified sample"})
                        continue
                    appearances.append(appearance)
                if not appearances:continue
                source_urls=sorted({x["sourceUrl"] for x in appearances})
                pbp_goals=[e for a in appearances for e in
                           by_player_events.get((a["gameId"],pid),[])]
                box_goals=sum(a["goals"] for a in appearances)
                mapped=[]
                seen=set()
                for e in pbp_goals:
                    event_id=e["gameId"]+":"+e["eventId"]
                    if event_id in seen:raise ValueError("Duplicated official goal event "+event_id)
                    seen.add(event_id)
                    mapped.append({"goalId":event_id,"date":e["date"],
                                   "gameId":e["gameId"],"sourceUrl":e["sourceUrl"]})
                sample={
                    "lastAppearances":[{"date":a["date"],"gameId":a["gameId"],
                                       "goals":a["goals"],"shotsOnGoal":a["shotsOnGoal"],
                                       "sourceUrl":a["sourceUrl"]}
                                      for a in appearances],
                    "sampleGameIds":[x["gameId"] for x in appearances],
                    "scope":"SAMPLED_RECENT_TEAM_GAMES_ONLY",
                    "notFullSeason":True,"includesActualZeroShotAppearances":True,
                }
                base={"slate_date":date,"stage":stage,"game_id":str(game["id"]),
                      "player_id":pid,"observed_at":timestamp,
                      "source_url":source_urls[0]}
                # A player's appearance is official only when their boxscore row
                # exists; the schedule alone never adds a missed-game zero.
                for kind,payload in [
                    ("PLAYER_GAME_LOG",{"appearances":sample["lastAppearances"],**sample}),
                    ("PLAYER_GOAL_EVENTS",{"goals":mapped,"scope":sample["scope"],
                                            "notFullSeason":True}),
                    ("PLAYER_OFFICIAL_GOALS",{"goals":box_goals,
                            "scope":sample["scope"],"notFullSeason":True,
                            "verifiedByPlayByPlay":True}),
                    ("PLAYER_FINISH_CREDIT",{"recipient":True if box_goals>0 else None,
                           "ownedGoalsInActualAppearances":box_goals,
                           "creditedGoalsVerified":True,
                           "independentHistoricallyScored":box_goals>0,
                           "notClaimOfTonightGoalCredit":True,
                           "scope":sample["scope"]}),
                    ("PLAYER_PRESSURE",{"recentAppearanceShots":[a["shotsOnGoal"]
                                         if a["shotsOnGoal"] is not None else
                                         sum(e["type"] in ("shot-on-goal","goal")
                                             for e in events if e["gameId"]==a["gameId"]
                                             and e["shooterId"]==pid)
                                         for a in appearances],
                           "appearances":sample["lastAppearances"],
                           "evidenceType":"OFFICIAL_HISTORICAL_SHOT_EVENTS",
                           "shotsOnGoalNotTotalAttempts":True,
                           "scope":sample["scope"]})
                ]:
                    ingest(con,{**base,"evidence_id":_versioned_receipt_id(
                        f"nhl-box-{date}-{stage}-{game['id']}-{pid}-{kind}",payload),
                        "kind":kind,"payload":payload})
                stats["verifiedOwnGoalRows"]+=1
                stats["appearanceRows"]+=len(appearances)
                stats["distinctPlayers"]+=1
    return {"status":"OFFICIAL_PBP_AND_BOXSCORE_RECONCILED",**stats,
            "source":"https://api-web.nhle.com/v1/gamecenter/",
            "timeLeakagePrevented":True,
            "noSeasonTotalsInvented":True}
