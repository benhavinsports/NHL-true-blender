"""Recover dated official goal ownership without widening recent-form samples.

These are retrospective source reconstructions, not original pregame captures.
Never use today's totals, a later goal, or a season count as a selection rule.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from nhl_true_blender_engine.season_goal_history import (
    decode_dated_goals, certified_zero_on_net_route)
from nhl_true_blender_engine.historical_shots import extract_events


def utc(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Historical evidence requires a timezone")
    return stamp.astimezone(timezone.utc)


def independent_owned_goal(proof, events):
    """Cross-check a dated positive game against its actual credited shooter."""
    pid = str(proof["playerId"])
    for game in proof["goalScoringGames"]:
        own = [e for e in events.get(game["gameId"], [])
               if str(e.get("shooterId")) == pid and e.get("type") == "goal"
               and e.get("date") == game["date"]
               and str(e.get("gameId")) == game["gameId"]
               and str(e.get("eventId", "")).isdigit()
               and e.get("sourceUrl") == (
                   "https://api-web.nhle.com/v1/gamecenter/"+game["gameId"]+"/play-by-play")]
        unique = {(str(e["gameId"]), str(e["eventId"])): e for e in own}
        if len(unique) == game["goals"]:
            return next(iter(unique.values()))
    return None


async def collect_historical_season_credits(client, con, day, games,
        club_schedules, cached_logs, cached_pbp, emit, source_failures):
    """Research every dated roster/deployment player before each game's lock.

    Cache source responses across slates, then independently trim every log
    to that slate. The original recent-eight appearance/event receipts remain
    untouched. No current roster, starter, EV role, or PP role is inferred.
    """
    start = int(day[:4]) if int(day[5:7]) >= 9 else int(day[:4])-1
    season = f"{start}{start+1}"
    scheduled = {str(g.get("id") or g.get("gameId")): g for g in games}
    past = {str(g["id"]): g for rows in club_schedules.values() for g in rows}
    targets = {}
    for row in con.execute(
            "SELECT game_id,player_id,observed_at FROM evidence WHERE slate_date=? "
            "AND kind IN ('PLAYER_DEPLOYMENT','PLAYER_GAME_LOG') "
            "AND stage IN ('PROJECTED','CONFIRMED')", (day,)):
        gid, pid = str(row["game_id"]), str(row["player_id"] or "")
        game = scheduled.get(gid)
        if not game or not pid.isdigit():
            continue
        deadline = utc(game.get("startUTC") or game.get("startTimeUTC"))-timedelta(minutes=5)
        if utc(row["observed_at"]) <= deadline:
            targets.setdefault(pid, {})[gid] = deadline
    sem = asyncio.Semaphore(6)

    async def log(pid):
        key = (pid, season)
        if key not in cached_logs:
            async with sem:
                try:
                    cached_logs[key] = await client.game_log(pid, season)
                except Exception as exc:
                    source_failures.append({"date": day, "playerId": pid,
                        "endpoint": "official-dated-season-log", "error": str(exc)[:180]})
        return pid, cached_logs.get(key)

    sourced = credits = zeros = 0
    for pid, raw in await asyncio.gather(*(log(pid) for pid in sorted(targets))):
        if not raw:
            continue
        proof = decode_dated_goals(raw["data"], pid, day)
        if not proof:
            continue
        # Every dated log row needs its own official completed-game clock.
        # A provider's current retrieval timestamp is never backdated.
        clocks = []
        valid = True
        for item in proof["datedGames"]:
            game = past.get(item["gameId"])
            if (not game or game.get("gameState") not in ("OFF", "FINAL", "GAME_OVER")
                    or not str(item["gameId"]).startswith(str(start)+"02")):
                valid = False
                break
            clocks.append(utc(game["startTimeUTC"])+timedelta(hours=6))
        if not valid or not clocks:
            continue
        available_at = max(clocks)
        eligible = [gid for gid, deadline in targets[pid].items()
                    if available_at <= deadline]
        if not eligible:
            continue
        proof["officialSourceUrl"] = raw["url"]
        proof["sourceRetrievedAtUTC"] = raw.get("observedAt")
        zero = certified_zero_on_net_route(proof)
        # A positive official log is independently checked against the dated
        # goal's PBP. It cannot manufacture ownership from an assist/feeder.
        for scoring in proof["goalScoringGames"]:
            gid = scoring["gameId"]
            if gid not in cached_pbp:
                try:
                    source = await client.play_by_play(gid)
                    cached_pbp[gid] = extract_events(source, gid, scoring["date"])
                except Exception as exc:
                    source_failures.append({"date": day, "gameId": gid,
                        "endpoint": "official-goal-credit-pbp", "error": str(exc)[:180]})
            if independent_owned_goal(proof, cached_pbp):
                break
        owned = independent_owned_goal(proof, cached_pbp)
        for gid in eligible:
            emit(con, day, "PROJECTED", gid, pid, "PLAYER_SEASON_HISTORY",
                 proof, [raw["url"]], available_at)
            if zero:
                emit(con, day, "PROJECTED", gid, pid, "PLAYER_ZERO_ON_NET_ROUTE",
                     zero, [raw["url"]], available_at)
                zeros += 1
            if owned:
                prior = con.execute(
                    "SELECT payload FROM evidence WHERE slate_date=? AND game_id=? "
                    "AND player_id=? AND kind='PLAYER_FINISH_CREDIT' "
                    "ORDER BY observed_at DESC,rowid DESC LIMIT 1", (day,gid,pid)).fetchone()
                recent_count = json.loads(prior["payload"]).get("ownedGoalsInActualAppearances") if prior else None
                emit(con, day, "PROJECTED", gid, pid, "PLAYER_FINISH_CREDIT", {
                    "recipient": True, "creditedGoalsVerified": True,
                    "ownedGoalsInActualAppearances": recent_count,
                    "independentHistoricallyScored": True,
                    "independentHistoricalGoalId": owned["gameId"]+":"+owned["eventId"],
                    "independentHistoricalGoalDate": owned["date"],
                    "scope": "DATED_SEASON_LOG_AND_INDEPENDENT_PBP_OWNERSHIP",
                    "notClaimOfTonightGoalCredit": True,
                    "recentAppearanceSampleUnchanged": True},
                    [raw["url"], owned["sourceUrl"]], available_at)
                credits += 1
        sourced += 1
    return {"queriedPlayers": len(targets), "sourcedPlayers": sourced,
            "independentlyVerifiedGoalCreditReceipts": credits,
            "verifiedSeasonZeroShotReceipts": zeros,
            "recentFormSampleUnchanged": True}
