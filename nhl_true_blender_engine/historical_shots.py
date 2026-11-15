"""Official NHL historical event evidence. Coordinates describe rink lanes, NOT
anatomical glove/blocker/five-hole weakness. Source identity and dates retained.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import date, datetime, timezone
from .enrichment import ingest

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
            "x": details.get("xCoord"), "y": details.get("yCoord"),
            "zone": details.get("zoneCode"),
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

async def collect_history(client, con, snapshot, slate_date, stage, max_games=8):
    """Only pre-slate historical games. Never leak today's or future outcomes."""
    teams = sorted({t for g in snapshot["games"] for t in (g["away"], g["home"])})
    # Official club schedule endpoint provides historical game IDs and dates.
    season_start = str(int(slate_date[:4]) if int(slate_date[5:7]) >= 9 else int(slate_date[:4])-1)
    season = season_start + str(int(season_start)+1)
    errors = []
    history = {}
    sem = asyncio.Semaphore(4)
    async def team_games(team):
        try:
            payload = await client.get(f"club-schedule-season/{team}/{season}")
            games = payload["data"].get("games", [])
            past = [g for g in games if str(g.get("gameDate", "")) < slate_date
                    and g.get("gameState") in ("OFF", "FINAL")]
            return team, past[-max_games:], None
        except Exception as exc:
            return team, [], str(exc)
    responses = await asyncio.gather(*(team_games(t) for t in teams))
    ids = {}
    for team, games, err in responses:
        if err:
            errors.append({"team": team, "error": err})
        for g in games:
            if g.get("id"):
                ids[str(g["id"])] = g.get("gameDate")
    async def one(game_id, played):
        async with sem:
            try:
                raw = await client.play_by_play(game_id)
                return game_id, extract_events(raw, game_id, played), None
            except Exception as exc:
                return game_id, [], str(exc)
    results = await asyncio.gather(*(one(g, d) for g, d in ids.items()))
    events = []
    for game_id, rows, err in results:
        if err:
            errors.append({"gameId": game_id, "error": err})
        else:
            events.extend(rows)
    for game in snapshot["games"]:
        for team in (game["away"], game["home"]):
            roster = (game.get("rosters", {}).get(team) or {}).get("data", {}).get("players", [])
            for player in roster:
                pid = player["id"]
                summary = shooter_summary(events, pid)
                if not summary["attempts"]:
                    continue
                urls = sorted({e["sourceUrl"] for e in events if e["shooterId"] == str(pid)})
                payload = {"recentAppearanceShots": summary["attempts"],
                           "shotsOnGoal": summary["shotsOnGoal"],
                           "ownedGoals": summary["ownedGoals"],
                           "byShotType": summary["byShotType"],
                           "historicalSourceUrls": urls,
                           "sampleGameIds": sorted({e["gameId"] for e in events if e["shooterId"] == str(pid)}),
                           "evidenceType": "OFFICIAL_HISTORICAL_SHOT_EVENTS"}
                ingest(con, {"evidence_id": f"historical-pressure-{slate_date}-{stage}-{game['id']}-{pid}",
                    "slate_date": slate_date, "stage": stage, "game_id": game["id"],
                    "player_id": pid, "kind": "PLAYER_PRESSURE",
                    "source_url": urls[0], "observed_at": datetime.now(timezone.utc).isoformat(),
                    "payload": payload})
    return {"historicalGames": len(ids), "shotEvents": len(events),
            "errors": errors, "goalieIdentityEvents": sum(e["goalieId"] is not None for e in events),
            "anatomicalGoalieWeaknessVerified": False}
