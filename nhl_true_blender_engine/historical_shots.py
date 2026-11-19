"""Official NHL historical event evidence. Coordinates describe rink lanes, NOT
anatomical glove/blocker/five-hole weakness. Source identity and dates retained.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from .enrichment import ingest
from .official_boxscore_history import collect_sampled_boxes
from .official_defense_coverage import make_coverage,conservative_zone,detailed_shot_origin_zone
from .shift_coverage import collect_shift_coverage
from .secondary_sources import TEAM_SLUGS

def _versioned_receipt_id(base,payload):
    """Append immutable source-data revisions; identical reruns stay idempotent."""
    digest=hashlib.sha256(json.dumps(
        payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
        ).hexdigest()[:20]
    return f"{base}-{digest}"


SHOT_TYPES = {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
ON_NET = {"goal", "shot-on-goal"}

def extract_events(raw, game_id, played_date):
    plays = raw["data"].get("plays", [])
    if not isinstance(plays, list):
        raise ValueError("Historical play-by-play missing plays")
    shots = []
    for event in plays:
        typ = event.get("typeDescKey")
        if typ not in SHOT_TYPES:
            continue
        if (event.get("periodDescriptor") or {}).get("periodType") == "SO":
            continue
        details = event.get("details") or {}
        shooter = details.get("shootingPlayerId") or details.get("scoringPlayerId")
        if not shooter:
            continue
        shots.append({
            "gameId": str(game_id), "date": played_date,
            "eventId": str(event.get("eventId") or event.get("sortOrder")),
            "shooterId": str(shooter),
            "goalieId": str(details["goalieInNetId"]) if details.get("goalieInNetId") else None,
            "type": typ, "shotType": details.get("shotType"),
            "period":(event.get("periodDescriptor") or {}).get("number"),
            "timeInPeriod":event.get("timeInPeriod"),
            "x": details.get("xCoord"), "y": details.get("yCoord"),
            "zone": details.get("zoneCode"),
            "ownerTeamId": str(details["eventOwnerTeamId"])
                            if details.get("eventOwnerTeamId") is not None else None,
            "sourceUrl": raw["url"]
        })
    return shots

def shooter_summary(events, player_id):
    own = [e for e in events if e["shooterId"] == str(player_id)]
    on_net = [e for e in own if e["type"] in ON_NET]
    goals = [e for e in own if e["type"] == "goal"]
    by_type = {}
    for e in own:
        k = e["shotType"] or "unknown"
        by_type.setdefault(k, {"attempts": 0, "goals": 0})
        by_type[k]["attempts"] += 1
        by_type[k]["goals"] += e["type"] == "goal"
    return {"attempts": len(own), "shotsOnGoal": len(on_net),
            "ownedGoals": len(goals), "byShotType": by_type,
            "appearanceDatesWithAttempts": sorted({e["date"] for e in own}),
            "goalEvents": goals}

def goalie_summary(events, goalie_id):
    own = [e for e in events if e["goalieId"] == str(goalie_id) and e["type"] in ON_NET]
    by_type = {}
    for e in own:
        k = e["shotType"] or "unknown"
        by_type.setdefault(k, {"shots": 0, "goalsAgainst": 0})
        by_type[k]["shots"] += 1
        by_type[k]["goalsAgainst"] += e["type"] == "goal"
    return {"shotsWithGoalieIdentity": len(own),
            "goalsAgainst": sum(e["type"] == "goal" for e in own),
            "byShotType": by_type,
            "anatomicalWeaknessVerified": False,
            "note": "Shot type and rink coordinates cannot establish glove/blocker/five-hole."}

def measured_recent_shooter_origins(events,player_id):
    """Positive, independently attributed, pre-slate shooter PBP origin proof.

    NHL play-by-play rink x/y is an APPROXIMATE shooting origin, never an
    anatomical goalie target nor an exact NHL EDGE tracking polygon.
    Only own goals/on-net shots count; assists and blocked/missed shots do not.
    """
    zones={}
    seen=set()
    for event in events:
        if (str(event.get("shooterId"))!=str(player_id)
            or event.get("type") not in ON_NET):
            continue
        key=(str(event.get("gameId")),str(event.get("eventId")))
        if key in seen:
            continue
        seen.add(key)
        labels=set(filter(None,(conservative_zone(event.get("x"),event.get("y")),
                                detailed_shot_origin_zone(event.get("x"),event.get("y")))))
        for name in labels:
            row=zones.setdefault(name,{"shotsOnGoal":0,"ownedGoals":0,
                                        "gameIds":set(),"sourceUrls":set()})
            row["shotsOnGoal"]+=1
            row["ownedGoals"]+=int(event["type"]=="goal")
            row["gameIds"].add(str(event["gameId"]))
            row["sourceUrls"].add(event["sourceUrl"])
    return {z:{"shotsOnGoal":r["shotsOnGoal"],"ownedGoals":r["ownedGoals"],
               "gameIds":sorted(r["gameIds"]),"sourceUrls":sorted(r["sourceUrls"])}
            for z,r in sorted(zones.items())}


async def collect_history(client, con, snapshot, slate_date, stage,
                          max_games=8, defense_research_games=16):
    """Collect target-team recent logs plus league-wide peer games for G9.

    The target clubs' recent games feed player logs, official boxscore
    reconciliation and shift joins. G9's peer median requires independent
    samples from at least six OTHER clubs; fetching only today's four teams'
    schedules made that impossible (all other teams had one game or fewer).
    Therefore fetch the larger, bounded pre-slate defensive comparison window
    from every NHL club, but keep the original eight latest team games for
    individual player goals, pressure, appearance logs and shift joins.
    Expanding G9 source research must NOT rewrite the player's recent sample.
    """
    target_teams=sorted({t for g in snapshot["games"] for t in (g["away"],g["home"])})
    league_teams=sorted(TEAM_SLUGS)
    season_start=str(int(slate_date[:4]) if int(slate_date[5:7])>=9 else int(slate_date[:4])-1)
    season=season_start+str(int(season_start)+1)
    errors=[];schedule_errors=[]
    sem=asyncio.Semaphore(8)
    async def team_games(team):
        async with sem:
            try:
                payload=await client.get(f"club-schedule-season/{team}/{season}")
                games=payload["data"].get("games",[])
                past=[g for g in games if str(g.get("gameDate",""))<slate_date
                      and g.get("gameState") in ("OFF","FINAL")]
                past.sort(key=lambda g:str(g.get("gameDate","")))
                return team,past[-max(max_games,defense_research_games):],None
            except Exception as exc:
                return team,[],f"{type(exc).__name__}: {exc}"
    responses=await asyncio.gather(*(team_games(t) for t in league_teams))
    target_ids={};coverage_ids={};game_meta={}
    for team,games,err in responses:
        if err:
            schedule_errors.append({"team":team,"error":err})
            continue
        # A longer independently sampled G9 defense cohort cannot silently
        # widen G7/G10/G12 recent-player history or invent extra appearances.
        recent_target_ids={str(g["id"]) for g in games[-max_games:]
                           if g.get("id")} if team in target_teams else set()
        for g in games:
            if not g.get("id"):
                continue
            gid=str(g["id"])
            coverage_ids[gid]=str(g.get("gameDate"))
            if gid in recent_target_ids:
                target_ids[gid]=str(g.get("gameDate"))
            away=g.get("awayTeam") or {}
            home=g.get("homeTeam") or {}
            game_meta[gid]={
                "homeTeamId":str(home["id"]) if home.get("id") is not None else None,
                "awayTeamId":str(away["id"]) if away.get("id") is not None else None,
                "homeAbbrev":home.get("abbrev"),
                "awayAbbrev":away.get("abbrev")}
    sem=asyncio.Semaphore(8)
    async def one(game_id,played):
        async with sem:
            try:
                raw=await client.play_by_play(game_id)
                return game_id,extract_events(raw,game_id,played),None
            except Exception as exc:
                return game_id,[],f"{type(exc).__name__}: {exc}"
    results=await asyncio.gather(*(one(gid,played) for gid,played in coverage_ids.items()))
    coverage_events=[];pbp_errors=[]
    for game_id,rows,err in results:
        if err:
            pbp_errors.append({"gameId":game_id,"error":err})
        else:
            coverage_events.extend(rows)
    # Distinguish an independently fetched PBP with zero goals from no PBP
    # at all. A failed source must not count as a reconciled zero appearance.
    pbp_verified_ids={str(gid) for gid,rows,err in results if err is None}
    target_events=[e for e in coverage_events if str(e["gameId"]) in target_ids]
    target_game_meta={gid:game_meta[gid] for gid in target_ids if gid in game_meta}
    # Only target-club games contribute to the candidate's actual appearances,
    # goal credits, pressure samples and historical defensive shift receipts.
    boxscore_receipts=await collect_sampled_boxes(
        client,con,snapshot,slate_date,stage,target_ids,target_events,
        pbp_verified_game_ids=pbp_verified_ids & set(target_ids))
    shift_receipts=await collect_shift_coverage(
        target_ids,target_events,target_game_meta)
    # G9 uses every club's independently sampled recent PBP attempts to build
    # a true league peer comparison; it never treats one-off opponents as a
    # six-game defensive sample.
    coverage_receipts=make_coverage(
        con,snapshot,slate_date,stage,coverage_events,game_meta,shift_receipts)
    for game in snapshot["games"]:
        for team in (game["away"],game["home"]):
            roster=(game.get("rosters",{}).get(team) or {}).get("data",{}).get("players",[])
            for player in roster:
                pid=player["id"]
                summary=shooter_summary(target_events,pid)
                if not summary["attempts"]:
                    continue
                urls=sorted({e["sourceUrl"] for e in target_events if e["shooterId"]==str(pid)})
                # Preserve dated, game-by-game positive shooter origin facts
                # for independent tie review in G10.5. This receipt is not a
                # fabricated future scorer and never overrides NHL EDGE goals.
                origins=measured_recent_shooter_origins(target_events,pid)
                if origins:
                    origin_urls=sorted({u for area in origins.values()
                                        for u in area["sourceUrls"]})
                    origin_payload={"sourceType":"OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN",
                        "scope":"RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY",
                        "zoneCounts":origins,"rinkBinsApproximateNotNhlEdgePolygons":True,
                        "historicalOwnGoalCreditOnly":True,
                        "notTonightGoalPrediction":True}
                    ingest(con,{"evidence_id":_versioned_receipt_id(
                            f"nhl-pbp-own-origins-{slate_date}-{stage}-{game['id']}-{pid}",
                            origin_payload),
                        "slate_date":slate_date,"stage":stage,"game_id":game["id"],
                        "player_id":pid,"kind":"PLAYER_RECENT_ORIGIN",
                        "source_url":origin_urls[0],
                        "observed_at":datetime.now(timezone.utc).isoformat(),
                        "payload":origin_payload})
                payload={"recentAppearanceShots":summary["attempts"],
                         "shotsOnGoal":summary["shotsOnGoal"],
                         "ownedGoals":summary["ownedGoals"],
                         "byShotType":summary["byShotType"],
                         "historicalSourceUrls":urls,
                         "sampleGameIds":sorted({e["gameId"] for e in target_events if e["shooterId"]==str(pid)}),
                         "evidenceType":"OFFICIAL_HISTORICAL_SHOT_EVENTS"}
                ingest(con,{"evidence_id":_versioned_receipt_id(
                        f"historical-pressure-{slate_date}-{stage}-{game['id']}-{pid}",payload),
                    "slate_date":slate_date,"stage":stage,"game_id":game["id"],
                    "player_id":pid,"kind":"PLAYER_PRESSURE",
                    "source_url":urls[0],"observed_at":datetime.now(timezone.utc).isoformat(),
                    "payload":payload})
    # Preserve every official target-player goal as a source-linked recipient event.
    for game in snapshot["games"]:
        for team in (game["away"],game["home"]):
            roster=(game.get("rosters",{}).get(team) or {}).get("data",{}).get("players",[])
            for player in roster:
                pid=str(player["id"])
                own=[e for e in target_events if e["shooterId"]==pid]
                if not own:
                    continue
                goals=[e for e in own if e["type"]=="goal"]
                urls=sorted({e["sourceUrl"] for e in own})
                observed=datetime.now(timezone.utc).isoformat()
                base={"slate_date":slate_date,"stage":stage,"game_id":game["id"],
                      "player_id":pid,"source_url":urls[0],"observed_at":observed}
                mapped=[{"goalId":e["gameId"]+":"+e["eventId"],
                         "date":e["date"],"sourceUrl":e["sourceUrl"]}
                        for e in goals]
                goal_payload={"goals":mapped,"scope":"SAMPLED_PRE_SLATE_GAMES_ONLY",
                              "completeSeason":False}
                ingest(con,{**base,
                    "evidence_id":_versioned_receipt_id(
                        f"historical-goals-{slate_date}-{stage}-{game['id']}-{pid}",goal_payload),
                    "kind":"PLAYER_GOAL_EVENTS","payload":goal_payload})
    errors=schedule_errors+pbp_errors
    return {"historicalGames":len(target_ids),"shotEvents":len(target_events),
            "coveragePeerGames":len(coverage_ids),
            "coveragePeerTeams":len(league_teams),
            "coveragePeerEvents":len(coverage_events),
            "G9IndependentPeerHistoryWindow":max(max_games,defense_research_games),
            "playerRecentHistoryWindowUnchanged":max_games,
            # Ephemeral in-process handoff. The driver POPs this before
            # writing run JSON; no extra raw league-wide events are persisted.
            # This pre-slate official PBP pool is also suitable for a fair
            # independently observed goalie-to-goalie shot-origin comparison.
            "_goaliePeerPbpEvents":coverage_events,
            "coveragePeerFetchFailures":len(pbp_errors),
            "teamScheduleSources":len(league_teams)-len(schedule_errors),
            "errors":errors,"goalieIdentityEvents":sum(e["goalieId"] is not None for e in target_events),
            "anatomicalGoalieWeaknessVerified":False,
            "boxscoreGoalLogReconciliation":boxscore_receipts,
            "defensiveCoverage":coverage_receipts,
            "historicalDefensiveShiftCoverage":{
                k:v for k,v in shift_receipts.items() if k!='byDefendingTeamId'},
            "G9PeerSampleIsLeagueWide":True,
            "candidateRecentLogsExcludeNonTargetPeerGames":True}
