"""Reconstruct pre-slate, event-bounded NHL PBP research for historical replay.

This is *research reconstruction*, not a claim that these source snapshots were
downloaded before their historical slate. Source event games must finish well
before the replay cutoff. Retrieval time and estimated availability are distinct.
Never infer starter identity, a player's upcoming line, or a scoring pick here.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import defaultdict
from scripts.historical_pregame_clock import first_issuance_windows, game_deadline
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from nhl_true_blender_engine.sources import NHLClient
from nhl_true_blender_engine.secondary_sources import TEAM_SLUGS
from nhl_true_blender_engine.historical_shots import (
    extract_events, measured_recent_shooter_origins, ON_NET,
    conservative_zone, detailed_shot_origin_zone)
from nhl_true_blender_engine.goalie_history_fallback import (
    summarize_goalie_origin_pbp, derive_independent_pbp_goalie_profile)
from nhl_true_blender_engine.enrichment import ingest
from nhl_true_blender_engine.official_defense_coverage import make_coverage
from nhl_true_blender_engine.shift_coverage import collect_shift_coverage
from nhl_true_blender_engine.storage import open_db
from scripts.historical_season_credits import collect_historical_season_credits

UTC = timezone.utc
# An explicit conservative *estimated* event-availability boundary. The source
# itself does not supply a historical HTTP publication timestamp.
FINISH_BUFFER = timedelta(hours=6)


def utc(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Official start/cutoff must be timezone-aware")
    return dt.astimezone(UTC)


def event_available_before(row, cutoff):
    """Never permit same-slate or later-game PBP into an earlier prediction."""
    start = row.get("startTimeUTC")
    if not start or row.get("gameState") not in ("OFF", "FINAL", "GAME_OVER"):
        return False
    try:
        return utc(start) + FINISH_BUFFER < cutoff
    except (TypeError, ValueError):
        return False


def league_pregame_games(schedules, cutoff, limit=18):
    """Stable, all-club historical peer cohort; no goalie/selection bias."""
    union = {}
    for rows in schedules.values():
        eligible = [r for r in rows if event_available_before(r, cutoff)]
        eligible.sort(key=lambda x: (x["startTimeUTC"], str(x["id"])))
        for row in eligible[-limit:]:
            union[str(row["id"])] = row
    return union


def _receipt(con, date, stage, game_id, player_id, kind, payload, urls, available_at):
    if not urls:
        return False
    # This timestamp is an *estimated historical source-availability clock*,
    # not a backdated claim that our crawler observed these bytes in the past.
    # Keep the actual reconstruction time in the payload for every receipt.
    payload = dict(payload)
    payload["historicalReconstruction"] = True
    payload["historicalSourceObservedAtCutoffVerified"] = False
    payload["replayAvailabilityClockBasis"] = "OFFICIAL_GAME_START_PLUS_SIX_HOURS"
    payload["reconstructedAtUTC"] = datetime.now(UTC).isoformat()
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:18]
    return ingest(con, {
        "evidence_id": "reconstructed-pbp-" + hashlib.sha256(
            f"{date}|{stage}|{game_id}|{player_id}|{kind}|{digest}".encode()
        ).hexdigest()[:32],
        "slate_date": date, "stage": stage, "game_id": str(game_id),
        "player_id": str(player_id) if player_id is not None else None,
        "kind": kind, "source_url": sorted(set(urls))[0],
        "observed_at": available_at.isoformat().replace("+00:00", "Z"),
        "payload": payload
    })


def _target_starters(con, date, games, cutoff):
    """Keep one latest report per independently identifiable goalie-source branch.

    Historical ledger archives may contain hundreds of revisions of the SAME
    pre-cutoff starter report. Repeated versions are not hundreds of different
    starters, and rebuilding a goalie profile for each falsely multiplies the
    evidence count. Never merge different goalie IDs, statuses or providers:
    genuine starter disagreements remain visible to the original G0 gate.
    """
    deadlines = {str(g.get("id") or g.get("gameId")):min(cutoff,game_deadline(g)) for g in games}
    ids = set(deadlines)
    unique = {}
    for row in con.execute(
        "SELECT * FROM evidence WHERE slate_date=? AND kind='GOALIE_STARTER' "
        "AND stage IN ('PROJECTED','CONFIRMED') ORDER BY observed_at, rowid",
        (date,)).fetchall():
        if str(row["game_id"]) not in ids or utc(row["observed_at"]) > deadlines[str(row["game_id"])]:
            continue
        d = json.loads(row["payload"])
        if (not d.get("goalieId") or d.get("status") not in
                ("PROJECTED", "EXPECTED", "CONFIRMED")):
            continue
        official = next((g for g in games
                         if str(g.get("id") or g.get("gameId")) == str(row["game_id"])), None)
        if not official or d.get("team") not in (official["away"], official["home"]):
            continue
        # The last independently dated revision of this exact evidence branch
        # supersedes redundant earlier copies. Distinct goalie candidates,
        # source URLs and projected/confirmed verdicts are NOT collapsed.
        key = (str(row["game_id"]), str(d["team"]), str(d["goalieId"]),
               str(d["status"]), str(row["stage"]), str(row["source_url"]))
        unique[key] = (row, d)
    return sorted(unique.values(), key=lambda pair: utc(pair[0]["observed_at"]))


def historical_goalie_peer_population(events, day):
    """Name the actual independent pre-slate PBP cohort, not today's starters.

    Both the G0 goalie comparison and later lane comparisons must retain this
    identity. A peer event correction changes it; starter/report order cannot.
    """
    signature = sorted(set(
        (str(e["gameId"]), str(e["eventId"]), str(e["goalieId"]),
         str(e["type"]), str(e["date"]))
        for e in events if e.get("goalieId") and e.get("type") in ON_NET))
    if not signature:
        return None
    return hashlib.sha256(json.dumps({
        "slate": day, "sampleEvents": signature,
        "referenceIndependentOfProjectedGoalies": True,
        "sourceScope": "ALL_NHL_CLUBS_PRE_SLATE_OFFICIAL_PBP"},
        sort_keys=True).encode()).hexdigest()[:20]


def _player_route(origin):
    """Use a player's own observed route; retain tied origins as unresolved."""
    ranked = sorted(
        ((zone, d) for zone, d in origin.items() if d["shotsOnGoal"] > 0),
        key=lambda x: (-x[1]["ownedGoals"], -x[1]["shotsOnGoal"], x[0]))
    if not ranked:
        return None
    key = (ranked[0][1]["ownedGoals"], ranked[0][1]["shotsOnGoal"])
    tied = [(zone, data) for zone, data in ranked
            if (data["ownedGoals"], data["shotsOnGoal"]) == key]
    if len(tied) > 1:
        # A historical top-area tie is not missing shooting evidence. Keep
        # every independently observed lane for the original engine's
        # opponent-specific G0/G9 comparison; do not choose a lane here.
        routes = [{"zone": z, "sog": d["shotsOnGoal"],
                   "ownedGoals": d["ownedGoals"], "sourceUrls": d["sourceUrls"]}
                  for z, d in ranked]
        return {"ambiguousRoutes": [r for r in routes
                    if (r["ownedGoals"], r["sog"]) == key],
                "allRoutes": routes, "canDeterminePrimary": False,
                "sourceType": "OFFICIAL_PRE_SLATE_PBP_SHOT_ORIGIN",
                "isAnatomicalReleaseClaim": False}
    zone, data = ranked[0]
    return {
        "archetype": "OBSERVED_OWN_SHOT_ORIGIN",
        "zone": zone, "attempts": data["shotsOnGoal"],
        "ownedGoals": data["ownedGoals"],
        "sourceType": "OFFICIAL_PRE_SLATE_PBP_SHOT_ORIGIN",
        "isAnatomicalReleaseClaim": False,
        "allRoutes": [
            {"zone": z, "sog": d["shotsOnGoal"], "ownedGoals": d["ownedGoals"],
             "sourceUrls": d["sourceUrls"]} for z, d in ranked]
    }


def build_player_recent_origin_sample(player_id, appearances, cached_pbp, slate_date, team):
    """Build a PBP lane sample aligned to actual, source-verified boxscore appearances.

    Zero-shot appearances remain in the denominator. A lane can be called zero
    only when every appearance has PBP coverage and every own on-net event has
    a dated, mappable rink origin.
    """
    sample_ids=[str(x.get("gameId") or "") for x in appearances]
    appearance_dates={str(x.get("gameId") or ""):str(x.get("date") or "")[:10]
                      for x in appearances}
    def game_events(gid):
        found=cached_pbp.get(gid)
        if found is None and gid.isdigit():
            found=cached_pbp.get(int(gid))
        return found or []
    sample_sources_by_game={
        gid:sorted({e.get("sourceUrl") for e in game_events(gid)
                    if isinstance(e.get("sourceUrl"),str)
                    and e["sourceUrl"].startswith("https://")})
        for gid in sample_ids if gid
    }
    player_events=[e for gid in sample_ids for e in game_events(gid)
                   if str(e.get("shooterId"))==str(player_id)]
    origins=measured_recent_shooter_origins(player_events,player_id)
    unmapped_onnet=0
    for event in player_events:
        if event.get("type") not in ON_NET:
            continue
        gid=str(event.get("gameId") or "")
        day=str(event.get("date") or "")[:10]
        has_origin=bool(conservative_zone(event.get("x"),event.get("y")) or
                        detailed_shot_origin_zone(event.get("x"),event.get("y")))
        if (not has_origin or not day or
                day!=appearance_dates.get(gid)):
            unmapped_onnet+=1
    dates_complete=all(
        isinstance(x.get("date"),str) and x["date"][:10]<slate_date
        for x in appearances)
    sample_complete=bool(appearances) and (
        len(sample_ids)==len(appearances) and
        len(sample_ids)==len(set(sample_ids)) and
        all(gid and gid in sample_sources_by_game and sample_sources_by_game[gid]
            for gid in sample_ids) and
        dates_complete and unmapped_onnet==0)
    source_urls=sorted({u for values in sample_sources_by_game.values() for u in values})
    payload={
        "sourceType":"OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN",
        "scope":"RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY",
        "zoneCounts":origins,
        "sampleAsOfSlateDate":slate_date,
        "sampleGameIds":sample_ids,
        "sampleAppearanceCount":len(sample_ids),
        "sampleSourcesByGame":sample_sources_by_game,
        "sampleCoverageComplete":sample_complete,
        "sampleIncludesActualZeroShotAppearances":True,
        "unclassifiedOnNetShots":unmapped_onnet,
        "sourceUrls":source_urls,
        "actualBoxscoreAppearancesUsed":True,
        "candidateTeamFromOfficialEventOwnerTeamId":team,
        "rinkBinsApproximateNotNhlEdgePolygons":True,
        "historicalOwnGoalCreditOnly":True,
        "notTonightGoalPrediction":True,
    }
    return payload,source_urls


async def reconstruct(manifest, database, output, limit=18):
    calendar = json.loads(Path(manifest).read_text())
    days = sorted(d for d, row in calendar["officialSchedule"].items() if row.get("games"))
    client = NHLClient()
    con = open_db(str(database))
    fetch_errors = []
    try:
        teams = sorted({team for d in days for g in calendar["officialSchedule"][d]["games"]
                        for team in (g["away"], g["home"])})
        starts = sorted({int(d[:4]) if int(d[5:7]) >= 9 else int(d[:4])-1
                         for d in days})
        seasons = sorted({f"{y}{y+1}" for y in starts} |
                         {f"{y-1}{y}" for y in starts})
        sem = asyncio.Semaphore(10)
        async def schedule(team, season):
            async with sem:
                try:
                    src = await client.get(f"club-schedule-season/{team}/{season}")
                    return team, season, src["data"].get("games") or [], None
                except Exception as e:
                    return team, season, [], type(e).__name__ + ": " + str(e)[:160]
        results = await asyncio.gather(
            *(schedule(team, season) for team in teams for season in seasons))
        club_schedules = defaultdict(dict)
        for team, season, rows, error in results:
            if error:
                fetch_errors.append({"team": team, "season": season, "error": error})
            for g in rows:
                if not g.get("id") or not g.get("startTimeUTC"):
                    continue
                item = dict(g)
                item["id"] = str(g["id"])
                club_schedules[team][item["id"]] = item
        club_schedules = {t: list(rows.values()) for t, rows in club_schedules.items()}
        cached_pbp = {}
        async def get_pbp(gid, game_date):
            if gid in cached_pbp:
                return cached_pbp[gid]
            async with sem:
                try:
                    raw = await client.play_by_play(gid)
                    value = extract_events(raw, gid, game_date)
                    return gid, value, None
                except Exception as e:
                    return gid, [], type(e).__name__ + ": " + str(e)[:160]
        cached_boxscores = {}
        cached_season_logs = {}
        cached_shifts = {}
        async def get_boxscore(game_id):
            async with sem:
                try:
                    source = await client.boxscore(game_id)
                    stats = source["data"].get("playerByGameStats")
                    if not isinstance(stats, dict):
                        raise ValueError("Official boxscore missing playerByGameStats")
                    return game_id, source, None
                except Exception as exc:
                    return game_id, None, type(exc).__name__ + ": " + str(exc)[:180]

        summary = []
        for date in days:
            games = calendar["officialSchedule"][date]["games"]
            cutoff = max(first_issuance_windows(games))
            pool = league_pregame_games(club_schedules, cutoff, limit)
            missing = [(gid, row) for gid, row in pool.items() if gid not in cached_pbp]
            collected = await asyncio.gather(*(
                get_pbp(gid, row.get("gameDate") or str(row["startTimeUTC"])[:10])
                for gid, row in missing))
            for gid, events, err in collected:
                if err:
                    fetch_errors.append({"date": date, "gameId": gid, "error": err})
                else:
                    cached_pbp[gid] = events
            # Only games with official starts + conservative finish buffer are
            # accepted. The newest accepted event determines reconstructed as-of.
            pool = {gid: r for gid, r in pool.items() if gid in cached_pbp}
            all_events = [e for gid in pool for e in cached_pbp[gid]]
            counts = summarize_goalie_origin_pbp(all_events)
            peer_population = historical_goalie_peer_population(all_events, date)
            peer_asof = max((utc(r["startTimeUTC"]) + FINISH_BUFFER
                             for r in pool.values()), default=None)
            snapshot = {"games": [
                {"id": str(g.get("id") or g.get("gameId")),
                 "away": g["away"], "home": g["home"]} for g in games]}
            game_meta = {
                gid: {"homeTeamId": str((r.get("homeTeam") or {}).get("id") or ""),
                      "awayTeamId": str((r.get("awayTeam") or {}).get("id") or ""),
                      "homeAbbrev": (r.get("homeTeam") or {}).get("abbrev"),
                      "awayAbbrev": (r.get("awayTeam") or {}).get("abbrev")}
                for gid, r in pool.items()}
            coverage_count = 0
            shift_report = {}
            if peer_asof and all_events:
                # The original Step8 needs actual on-ice intervals joined
                # to prior PBP events. Coverage counts alone cannot supply
                # that receipt. Only this already cutoff-filtered pool is
                # joined, even when later slates reuse downloaded charts.
                shift_report = await collect_shift_coverage(
                    {gid: str(r.get('gameDate') or r['startTimeUTC'][:10])
                     for gid,r in pool.items()}, all_events, game_meta)
                report = make_coverage(
                    con, snapshot, date, "PROJECTED", all_events, game_meta, shift_report,
                    historical_replay_observed_at=peer_asof.isoformat())
                coverage_count = report["coverageAttackSides"]
            context_count = 0
            for game in snapshot["games"]:
                previous = {}
                for team in (game["away"], game["home"]):
                    past = sorted((r for r in club_schedules.get(team, [])
                                   if r["id"] in pool),
                                  key=lambda r: r["startTimeUTC"])
                    if past:
                        previous[team] = past[-1]
                if len(previous) != 2:
                    continue
                away, home = (previous[game[key]] for key in ("away", "home"))
                away_date = str(away.get("gameDate") or away["startTimeUTC"][:10])[:10]
                home_date = str(home.get("gameDate") or home["startTimeUTC"][:10])[:10]
                today = datetime.fromisoformat(date).date()
                away_rest = (today - datetime.fromisoformat(away_date).date()).days - 1
                home_rest = (today - datetime.fromisoformat(home_date).date()).days - 1
                if not (0 <= away_rest <= 10 and 0 <= home_rest <= 10):
                    continue
                asof = max(utc(r["startTimeUTC"]) + FINISH_BUFFER for r in (away, home))
                if asof >= cutoff:
                    continue
                _receipt(con, date, "PROJECTED", game["id"], None,
                         "MATCH_CONTEXT", {
                             "venueHome": game["home"], "awayRestDays": away_rest,
                             "homeRestDays": home_rest,
                             "awayLastGameDate": away_date,
                             "homeLastGameDate": home_date,
                             "travelDistanceNotInSource": True,
                             "sourceType": "OFFICIAL_PRE_SLATE_GAME_SCHEDULE_AND_REST"},
                         ["https://api-web.nhle.com/v1/schedule/" + date], asof)
                context_count += 1
            starters = _target_starters(con, date, games, cutoff)
            profiles = 0
            peer_qualified = 0
            for starter, data in starters:
                pid = str(data["goalieId"])
                profile = derive_independent_pbp_goalie_profile(pid, counts, peer_counts=counts)
                if not profile:
                    continue
                own_games = set(profile["sample"]["historicalGameIds"])
                sampled = [pool[gid] for gid in own_games if gid in pool]
                if not sampled:
                    continue
                # Percentiles depend on the whole independent peer sample,
                # not just this starter's own games. Retain the latest source
                # availability needed to reproduce that comparison.
                available_at = max(
                    max(utc(g["startTimeUTC"]) + FINISH_BUFFER for g in sampled),
                    peer_asof)
                if available_at >= cutoff or not peer_population:
                    continue
                for area in profile.get("observedAreas", {}).values():
                    area["samplePeerPopulationId"] = peer_population
                    area["samplePeerPopulationStable"] = True
                profile.update({
                    "samplePeerPopulationId": peer_population,
                    "samplePeerPopulationStable": True,
                    "peerSampleNeverLeagueEDGEPercentile": True,
                    "goalieId": pid, "team": data["team"], "status": data["status"],
                    "sourceReviewed": profile["fullySourceComparedAreas"] > 0,
                    "historicalSampleAsOf": date,
                    "historicalSampleGameIds": sorted(own_games),
                    "starterSourceUrl": starter["source_url"],
                    "independentGoalieIdentityVerifiedByPbp": True,
                    "peerCohort": "ALL_NHL_CLUBS_PRE_SLATE_OFFICIAL_PBP",
                    "notGoalMouthAnatomy": True
                })
                sources = profile["historicalPbpSources"]
                _receipt(con, date, starter["stage"], starter["game_id"], pid,
                         "GOALIE_PROFILE", profile, sources, available_at)
                # Preserve the same independent comparison supplement used
                # by main's live collector. This never changes starter status
                # or substitutes a different goalie profile.
                _receipt(con, date, starter["stage"], starter["game_id"], pid,
                         "GOALIE_PBP_PEER_CONTEXT", profile, sources, available_at)
                profiles += 1
                peer_qualified += int(profile["fullySourceComparedAreas"] > 0)

            # Player origin and release receipts are built below only after the
            # actual pre-slate boxscore appearance denominator is reconstructed.
            player_receipts = 0
            # Reconstruct actual PRE-SLATE skater appearances from official
            # boxscores. This is neither today's dressed roster nor a
            # projected line/PP assignment, and is never used to infer either.
            recent_games_by_team = {}
            box_ids = set()
            active_teams = {t for g in games for t in (g["away"], g["home"])}
            for team in active_teams:
                past = sorted(
                    (row for row in club_schedules.get(team, [])
                     if row["id"] in pool), key=lambda row: row["startTimeUTC"])
                recent_games_by_team[team] = past[-8:]
                box_ids.update(row["id"] for row in past[-8:])
            fresh_boxes = sorted(box_ids - set(cached_boxscores))
            for box_gid, raw, error in await asyncio.gather(
                    *(get_boxscore(gid) for gid in fresh_boxes)):
                if raw:
                    cached_boxscores[box_gid] = raw
                else:
                    fetch_errors.append({"date": date, "gameId": box_gid,
                                         "endpoint": "official-boxscore",
                                         "error": error})
            team_appearances = defaultdict(lambda: defaultdict(list))
            for team, recent in recent_games_by_team.items():
                for previous in recent:
                    box = cached_boxscores.get(previous["id"])
                    if not box:
                        continue
                    side = (
                        "homeTeam" if (previous.get("homeTeam") or {}).get("abbrev") == team
                        else "awayTeam" if (previous.get("awayTeam") or {}).get("abbrev") == team
                        else None)
                    if not side:
                        continue
                    data = box["data"]["playerByGameStats"].get(side) or {}
                    for group in ("forwards", "defense"):
                        for row in data.get(group) or []:
                            pid = row.get("playerId")
                            # NHL gamecenter boxscores expose SOG as "sog".
                            # The old "shots"-only branch discarded every
                            # officially recorded historical appearance.
                            shots = (row.get("sog") if type(row.get("sog")) is int
                                     else row.get("shots"))
                            goals = row.get("goals")
                            if (pid is None or type(shots) is not int or shots < 0
                                    or type(goals) is not int or goals < 0):
                                continue
                            played = str(previous.get("gameDate") or
                                         previous["startTimeUTC"][:10])[:10]
                            if played >= date:
                                continue
                            team_appearances[team][str(pid)].append({
                                "date": played, "gameId": previous["id"],
                                "goals": goals, "shotsOnGoal": shots,
                                "sourceUrl": box["url"]})
            box_log_receipts = 0
            reconciled_recipient_receipts = 0
            for scheduled in games:
                upcoming_id = str(scheduled.get("id") or scheduled.get("gameId"))
                for team in (scheduled["away"], scheduled["home"]):
                    for pid, appearances in team_appearances[team].items():
                        appearances.sort(
                            key=lambda a: (a["date"], a["gameId"]), reverse=True)
                        game_ids = {x["gameId"] for x in appearances}
                        historical_games = [pool[x] for x in game_ids]
                        available_at = max(utc(x["startTimeUTC"]) + FINISH_BUFFER
                                           for x in historical_games)
                        if available_at >= cutoff:
                            continue
                        urls = [a["sourceUrl"] for a in appearances]
                        scope = "SAMPLED_RECENT_TEAM_GAMES_ONLY"
                        log = {
                            "lastAppearances": appearances,
                            "appearances": appearances,
                            "sampleGameIds": sorted(game_ids),
                            "scope": scope, "notFullSeason": True,
                            "includesActualZeroShotAppearances": True,
                            "notEvidenceOfTonightDressedRoster": True}
                        _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                 "PLAYER_GAME_LOG", log, urls, available_at)
                        _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                 "PLAYER_PRESSURE", {
                                     "recentAppearanceShots": [x["shotsOnGoal"]
                                                               for x in appearances],
                                     "appearances": appearances,
                                     "evidenceType": "OFFICIAL_HISTORICAL_SHOT_EVENTS",
                                     "shotsOnGoalNotTotalAttempts": True,
                                     "scope": scope,
                                     "notTonightDeploymentEvidence": True},
                                 urls, available_at)
                        # Only now do we have the exact actual-appearance
                        # denominator. Include zero-shot appearances and every
                        # game's PBP source; incomplete coverage remains pending.
                        origin_payload, origin_urls = build_player_recent_origin_sample(
                            pid, appearances, cached_pbp, date, team)
                        if origin_urls:
                            if _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                        "PLAYER_RECENT_ORIGIN", origin_payload,
                                        origin_urls, available_at) is not False:
                                player_receipts += 1
                            if origin_payload["sampleCoverageComplete"]:
                                route = _player_route(origin_payload["zoneCounts"])
                                if route:
                                    _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                             "PLAYER_RELEASE", route, origin_urls,
                                             available_at)
                        box_log_receipts += 1
                        owned = [event for game_id in game_ids
                                 for event in cached_pbp[game_id]
                                 if (event["shooterId"] == pid and
                                     event["type"] == "goal")]
                        scored = sum(x["goals"] for x in appearances)
                        if scored != len(owned):
                            # Boxscore/PBP disagreement must never certify
                            # scoring credit or a positive finishing recipient.
                            continue
                        mapped = [{"goalId": e["gameId"] + ":" + e["eventId"],
                                   "date": e["date"], "gameId": e["gameId"],
                                   "sourceUrl": e["sourceUrl"]} for e in owned]
                        _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                 "PLAYER_GOAL_EVENTS", {
                                     "goals": mapped, "scope": scope,
                                     "notFullSeason": True,
                                     "verifiedByPlayByPlay": True},
                                 urls, available_at)
                        _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                 "PLAYER_OFFICIAL_GOALS", {
                                     "goals": scored, "scope": scope,
                                     "notFullSeason": True,
                                     "verifiedByPlayByPlay": True},
                                 urls, available_at)
                        _receipt(con, date, "PROJECTED", upcoming_id, pid,
                                 "PLAYER_FINISH_CREDIT", {
                                     "recipient": True if scored > 0 else None,
                                     "ownedGoalsInActualAppearances": scored,
                                     "creditedGoalsVerified": True,
                                     "independentHistoricallyScored": scored > 0,
                                     "notClaimOfTonightGoalCredit": True,
                                     "scope": scope},
                                 urls, available_at)
                        reconciled_recipient_receipts += 1
            season_credits = await collect_historical_season_credits(
                client, con, date, games, club_schedules, cached_season_logs,
                cached_pbp, _receipt, fetch_errors)
            summary.append({
                "officialDatedSeasonCreditCoverage": season_credits,
                "date": date, "games": len(games), "goalieStartersWithDatedEvidence": len(starters),
                "independentGoalieProfilesImported": profiles,
                "goalieProfilesWithPeerComparedAreas": peer_qualified,
                "playerRecentOriginReceipts": player_receipts,
                "historicalBoxscorePlayerLogs": box_log_receipts,
                "boxscorePbpReconciledRecipients": reconciled_recipient_receipts,
                "historicalTeamCoverageDirections": coverage_count,
                "historicalShiftChartGames": shift_report.get('chartedGames',0),
                "historicalShiftMatchedShotEvents": shift_report.get('matchedDefensiveShotEvents',0),
                "historicalShiftSourceFailures": shift_report.get('sourceFailures',[]),
                "officialMatchContextReceipts": context_count,
                "allInputsFromPriorFinishedOfficialGames": True,
                "archivePublicationTimestampIndependentlyVerified": False
            })
            con.commit()
        report = {
            "period": [days[0], days[-1]] if days else [],
            "scheduledSlatesResearched": len(summary),
            "totalGoalieProfiles": sum(x["independentGoalieProfilesImported"] for x in summary),
            "totalPeerQualifiedGoalieProfiles": sum(x["goalieProfilesWithPeerComparedAreas"] for x in summary),
            "totalPlayerRecentOriginReceipts": sum(x["playerRecentOriginReceipts"] for x in summary),
            "totalHistoricalBoxscorePlayerLogs": sum(x["historicalBoxscorePlayerLogs"] for x in summary),
            "totalBoxscorePbpReconciledRecipients": sum(x["boxscorePbpReconciledRecipients"] for x in summary),
            "totalTeamCoverageDirections": sum(x["historicalTeamCoverageDirections"] for x in summary),
            "totalShiftMatchedShotEvents": sum(x['historicalShiftMatchedShotEvents'] for x in summary),
            "uniqueOfficialShiftChartsCached": len(cached_shifts),
            "totalMatchContextReceipts": sum(x["officialMatchContextReceipts"] for x in summary),
            "days": summary, "sourceFailures": fetch_errors[:200],
            "actualSourceRetrievalIsLaterThanHistoricalCutoff": True,
            "estimatedReplayAsOfIsNotARealCollectorObservedTimestamp": True,
            "noUpcomingStartersOrPlayerDeploymentInferred": True
        }
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print(json.dumps({k: v for k, v in report.items()
                          if k not in ("days", "sourceFailures")}, sort_keys=True))
        return report
    finally:
        con.close()
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--database", type=Path,
                        default=Path("state/true_blender.sqlite"))
    parser.add_argument("--output", type=Path,
                        default=Path("state/replay/historical-pbp-reconstruction.json"))
    parser.add_argument("--per-team-games", type=int, default=18)
    args = parser.parse_args()
    if args.per_team_games < 1:
        parser.error("--per-team-games must be positive")
    asyncio.run(reconstruct(args.manifest, args.database, args.output,
                            args.per_team_games))


if __name__ == "__main__":
    main()
