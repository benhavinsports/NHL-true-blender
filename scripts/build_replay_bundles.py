"""Rebuild point-in-time replay bundles from the canonical evidence ledger.

Only dates with a completed engine job, official schedule, and pre-cutoff source
receipts are bundled. An original card is not required. Missing dates are never fabricated.
"""
from __future__ import annotations
import argparse
import asyncio
import gzip
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.sources import normalize_games
from nhl_true_blender_engine.storage import open_db, record_evidence
from nhl_true_blender_engine.sources import NHLClient

RAW_DB = Path("state/true_blender.sqlite")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _date_inventory(payload, kind):
    """Extract only dated historical observations; do not confuse schedule dates with events."""
    dates = set()
    as_of = set()
    def walk(value, key=None):
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str) and len(v) >= 10:
                    if k in ("asOf", "asOfDate", "historicalSampleAsOf", "publishedAsOfSlateDate",
                             "lastUpdated", "updatedAt", "publishedAt"):
                        as_of.add(v)
                    elif k in ("date", "gameDate", "eventDate", "lastGameDate",
                               "awayLastGameDate", "homeLastGameDate"):
                        dates.add(v[:10])
                walk(v, k)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
    if kind not in ("GAME_SCHEDULE",):
        walk(payload)
    if kind == "MATCH_CONTEXT":
        dates = set()
        for key in ("awayLastGameDate", "homeLastGameDate"):
            value = payload.get(key)
            if isinstance(value, str):
                dates.add(value[:10])
    # These fields describe the slate/provider's as-of label, not an event
    # occurring on the slate date.
    dates = {x for x in dates if x}
    return sorted(dates), sorted(as_of)


def build_day(source, day, out, schedule_row):
    """Build a slate from dated evidence without requiring an old engine job or saved card.

    The replay cutoff is derived from the official first puck-drop time. Cards,
    prior engine jobs, grades and outcomes are never used to decide whether a
    slate can be reconstructed.
    """
    scheduled_games = schedule_row.get("games") or []
    if not scheduled_games:
        return None
    # Official calendar uses gameId; engine snapshots use id. Normalize once.
    normalized_schedule_games = []
    starts = []
    for source_game in scheduled_games:
        game = dict(source_game)
        game["id"] = str(game.get("id") or game.get("gameId") or "")
        start_value = game.get("startTimeUTC") or game.get("startUTC")
        if not game["id"] or not start_value:
            raise ValueError(f"Official schedule game missing identity or start time: {day}: {source_game}")
        game["startTimeUTC"] = start_value
        starts.append(datetime.fromisoformat(start_value.replace("Z", "+00:00")))
        normalized_schedule_games.append(game)
    scheduled_games = normalized_schedule_games
    # Freeze the entire slate at the first puck drop. Later-game receipts
    # require a separately modeled per-game replay, not a later global clock.
    first_start = min(starts)
    cutoff_dt = first_start - timedelta(minutes=5)
    cutoff = cutoff_dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    # Keep the projected/confirmed evidence branches distinct. Prefer a
    # confirmed evidence set only when confirmed receipts actually exist.
    all_rows = source.execute(
        "SELECT * FROM evidence WHERE slate_date=? ORDER BY observed_at, rowid", (day,)
    ).fetchall()
    eligible = [r for r in all_rows if r["stage"] in ("OFFICIAL", "PROJECTED", "CONFIRMED")]
    rows = [r for r in eligible if datetime.fromisoformat(
        r["observed_at"].replace("Z", "+00:00")) <= cutoff_dt]
    # A date with no same-day receipts may still have legitimate pre-cutoff
    # archived observations from earlier dates. Preserve the scheduled slate
    # and let the engine report missing evidence instead of silently dropping
    # that date from the historical calendar.
    # A goalie confirmation is NOT a confirmation of the entire skater slate.
    # Promoting all players to CONFIRMED because a single DFO GOALIE_STARTER
    # receipt was confirmed made historical G2/G6 require absent confirmed
    # dressed skaters and confirmed lines, blocking every otherwise valid
    # projected replay. Require independently observed confirmed player
    # availability AND deployment across both clubs in every matchup before
    # considering the slate a fully confirmed skater snapshot.
    def confirmed_team_players(team, game_id):
        roster = [
            json.loads(r["payload"]) for r in rows
            if r["kind"] == "TEAM_CURRENT_ROSTER"
            and r["stage"] == "OFFICIAL"
            and json.loads(r["payload"]).get("team") == team
        ]
        if not roster:
            return False
        roster_ids = {str(p.get("id")) for p in roster[-1].get("players", [])
                      if p.get("id") is not None}
        actual = set()
        deployed = set()
        for r in rows:
            if str(r["game_id"]) != game_id or r["stage"] != "CONFIRMED":
                continue
            pid = str(r["player_id"] or "")
            if pid not in roster_ids:
                continue
            payload = json.loads(r["payload"])
            if (r["kind"] == "PLAYER_STATUS"
                    and payload.get("status") in ("DRESSED", "CONFIRMED")):
                actual.add(pid)
            if (r["kind"] == "PLAYER_DEPLOYMENT"
                    and payload.get("status") == "CONFIRMED"
                    and payload.get("EV")):
                deployed.add(pid)
        # Match the official game's documented minimum complete skater
        # membership; individual confirmed skaters do not confirm a team.
        return len(actual & deployed) >= 15

    stage = "CONFIRMED" if all(
        confirmed_team_players(team, str(g["id"]))
        for g in scheduled_games
        for team in (g["away"], g["home"])
    ) else "PROJECTED"

    schedules = [r for r in rows if r["kind"] == "GAME_SCHEDULE" and r["stage"] == "OFFICIAL"]
    if schedules:
        schedule = schedules[-1]
        schedule_data = json.loads(schedule["payload"])
        games = normalize_games({
            "data": schedule_data, "url": schedule["source_url"],
            "observedAt": schedule["observed_at"]
        }, day)
        # The immutable official calendar is the authority for scheduled
        # matchups; reject a mismatch rather than silently replaying another slate.
        expected = {(str(g.get("id")), g.get("away"), g.get("home")) for g in scheduled_games}
        actual = {(str(g.get("id")), g.get("away"), g.get("home")) for g in games}
        if expected != actual:
            raise ValueError(f"Archived GAME_SCHEDULE receipts do not match official calendar for {day}")
    else:
        # The frozen official calendar can reconstruct game identity and start
        # times, but never substitutes for player/goalie/lineup evidence.
        games = [{
            "id": str(g["id"]), "date": day, "away": g["away"], "home": g["home"],
            "startUTC": g["startTimeUTC"], "gameState": "FUT",
            "officialSourceUrl": schedule_row.get("source"),
            "officialObservedAt": schedule_row.get("downloadedAt"),
            "goalies": {}, "rosters": {}, "context": {}, "coverage": {}
        } for g in scheduled_games]

    rosters = {}
    for row in rows:
        if row["kind"] != "TEAM_CURRENT_ROSTER" or row["stage"] != "OFFICIAL":
            continue
        data = json.loads(row["payload"])
        team = data.get("team")
        if team:
            rosters[team] = {"sourceUrl": row["source_url"],
                             "observedAt": row["observed_at"],
                             "evidenceId": row["evidence_id"], "data": data}
    # Reuse an earlier observed official roster only if it existed before
    # this slate's cutoff. Never backfill with a present-day roster or
    # postgame boxscore participants.
    needed_teams = {team for game in games for team in (game["away"], game["home"])}
    missing_teams = needed_teams - set(rosters)
    carry_rows = []
    if missing_teams:
        candidates = source.execute(
            """SELECT * FROM evidence
               WHERE kind='TEAM_CURRENT_ROSTER' AND stage='OFFICIAL'
                 AND slate_date<=? AND observed_at<=?
               ORDER BY observed_at DESC, rowid DESC""",
            (day, cutoff),
        ).fetchall()
        for row in candidates:
            data = json.loads(row["payload"])
            team = data.get("team")
            if team not in missing_teams or not isinstance(data.get("players"), list):
                continue
            rosters[team] = {"sourceUrl": row["source_url"],
                             "observedAt": row["observed_at"],
                             "evidenceId": row["evidence_id"], "data": data}
            carry_rows.append(row)
            missing_teams.remove(team)
            if not missing_teams:
                break
    for game in games:
        game["rosters"] = {team: rosters.get(team) for team in (game["away"], game["home"])}
    # A goalie-specific scouting profile may have been observed before an
    # earlier slate and remains valid historical evidence for that SAME goalie.
    # The old builder only selected slate_date=day, discarding that evidence
    # even when today's independent starter receipt identified the goalie.
    # Carry the original observation into the isolated replay only; never
    # alter the canonical evidence ledger or infer a goalie weakness.
    existing_profiles = {
        (str(r["game_id"]), str(json.loads(r["payload"]).get("goalieId")))
        for r in rows if r["kind"] == "GOALIE_PROFILE"
    }
    carried_profiles = []
    for starter in (r for r in rows if r["kind"] == "GOALIE_STARTER"):
        starter_data = json.loads(starter["payload"])
        goalie_id = str(starter_data.get("goalieId") or "")
        team = starter_data.get("team")
        game_id = str(starter["game_id"])
        if not goalie_id or not team or (game_id, goalie_id) in existing_profiles:
            continue
        historical = source.execute(
            """SELECT * FROM evidence
               WHERE kind='GOALIE_PROFILE' AND slate_date<=?
                 AND observed_at<=? AND observed_at<=?
               ORDER BY observed_at DESC, rowid DESC""",
            (day, cutoff, starter["observed_at"]),
        ).fetchall()
        for old in historical:
            profile = json.loads(old["payload"])
            if str(profile.get("goalieId") or "") != goalie_id or profile.get("team") != team:
                continue
            # Preserve the exact original scouting payload and source URL.
            # A new derived receipt links it to today's verified starter;
            # its observation timestamp remains the original pregame time.
            carried_profiles.append({
                "evidence_id": "replay-carry-" + sha256(
                    f'{day}|{game_id}|{old["evidence_id"]}'.encode())[:32],
                "slate_date": day, "stage": old["stage"],
                "game_id": game_id, "player_id": old["player_id"],
                "kind": old["kind"], "source_url": old["source_url"],
                "observed_at": old["observed_at"], "payload": profile,
            })
            existing_profiles.add((game_id, goalie_id))
            break
    snapshot = {"games": games}

    out.mkdir(parents=True, exist_ok=True)
    evidence_path = out / f"{day}-evidence.sqlite"
    con = open_db(str(evidence_path))
    try:
        for row in [*rows, *carry_rows, *carried_profiles]:
            record_evidence(con, {
                "evidence_id": row["evidence_id"], "slate_date": row["slate_date"],
                "stage": row["stage"], "game_id": row["game_id"],
                "player_id": row["player_id"], "kind": row["kind"],
                "source_url": row["source_url"], "observed_at": row["observed_at"],
                "payload": json.loads(row["payload"])
            })
        attach(con, snapshot, day, stage)
    finally:
        con.close()

    snapshot_bytes = json.dumps(snapshot, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False).encode()
    snapshot_path = out / f"{day}-snapshot.json"
    snapshot_path.write_bytes(snapshot_bytes)
    db_bytes = evidence_path.read_bytes()
    compressed_path = out / f"{day}-evidence.sqlite.gz"
    compressed_path.write_bytes(gzip.compress(db_bytes, compresslevel=6, mtime=0))
    evidence_path.unlink()

    grouped = {}
    for row in [*rows, *carry_rows, *carried_profiles]:
        key = (row["kind"], row["source_url"])
        item = grouped.setdefault(key, {
            "kind": row["kind"], "source": row["source_url"],
            "collectorObservedAtEarliest": row["observed_at"],
            "collectorObservedAtLatest": row["observed_at"],
            "receiptCount": 0, "underlyingEventDates": set(),
            "providerAsOfLabels": set(),
        })
        item["receiptCount"] += 1
        item["collectorObservedAtEarliest"] = min(item["collectorObservedAtEarliest"], row["observed_at"])
        item["collectorObservedAtLatest"] = max(item["collectorObservedAtLatest"], row["observed_at"])
        event_dates, as_of = _date_inventory(json.loads(row["payload"]), row["kind"])
        item["underlyingEventDates"].update(event_dates)
        item["providerAsOfLabels"].update(as_of)
    inputs = []
    for item in grouped.values():
        dates = sorted(item.pop("underlyingEventDates"))
        as_of = sorted(item.pop("providerAsOfLabels"))
        item["underlyingEventDateRange"] = [dates[0], dates[-1]] if dates else None
        item["underlyingEventDateCount"] = len(dates)
        item["providerAsOfLabels"] = as_of
        item["providerAvailabilityTime"] = "NOT_INDEPENDENTLY_CAPTURED"
        item["timeBasis"] = (
            "DATED_HISTORICAL_EVENTS" if dates else
            "PROVIDER_DATE_LABEL_ONLY" if as_of else
            "PROVIDER_EVENT_WINDOW_NOT_EXPOSED")
        inputs.append(item)
    inputs.sort(key=lambda x: (x["kind"], x["source"] or ""))
    return {
        "stage": stage, "cutoff": cutoff,
        "snapshot": snapshot_path.name, "snapshotSha256": sha256(snapshot_bytes),
        "evidenceDb": compressed_path.name, "evidenceDbSha256": sha256(compressed_path.read_bytes()),
        "inputs": inputs, "gameCount": len(games),
        "teamsWithOfficialRoster": sorted(rosters),
        "historicalRosterCarryForwardCount": len(carry_rows),
        "historicalGoalieProfileCarryForwardCount": len(carried_profiles),
        "teamsMissingHistoricalRoster": sorted(missing_teams),
        "collectorObservedAtBeforeCutoff": True,
        "providerAvailabilityTimeIndependentlyVerified": False,
        "underlyingEventDateAudit": "KNOWN_DATED_EVENT_FIELDS_EXTRACTED; UNDATED_PROVIDER_AGGREGATES_REMAIN_UNVERIFIED"
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path, default=Path("state/replay"))
    parser.add_argument("--schedule", type=Path, default=Path("state/replay/official_schedule.json"))
    args = parser.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if end < start:
        parser.error("--end must not precede --start")
    if not RAW_DB.is_file():
        raise SystemExit("Canonical database missing; restore state/true_blender.sqlite.gz first")
    args.output.mkdir(parents=True, exist_ok=True)
    # The workflow fetches the official NHL calendar immediately before
    # this builder. Consume that verified file; calendar retrieval belongs to
    # fetch_official_slate_calendar.py, not this bundle module.
    if not args.schedule.is_file():
        raise SystemExit("Official NHL schedule calendar missing; workflow fetch step must complete first")
    official_calendar = json.loads(args.schedule.read_text(encoding="utf-8"))
    if official_calendar.get("start") != start.isoformat() or official_calendar.get("end") != end.isoformat():
        raise SystemExit("Official NHL schedule calendar date range does not match requested replay window")
    calendar_days = official_calendar.get("calendarDays")
    if not isinstance(calendar_days, list):
        raise SystemExit("Official NHL schedule calendar lacks calendarDays")
    official_schedule_by_date = {
        row["date"]: {
            "source": row.get("officialSourceUrl"),
            "downloadedAt": row.get("downloadedAt"),
            "schedulePublicationTime": row.get("schedulePublicationTime"),
            "games": row.get("games") or [],
            "verifiedOffDay": not bool(row.get("games")),
        }
        for row in calendar_days
        if start.isoformat() <= row["date"] <= end.isoformat()
    }
    if set(official_schedule_by_date) != {
        (start.fromordinal(start.toordinal() + n)).isoformat()
        for n in range((end-start).days + 1)
    }:
        raise SystemExit("Official NHL schedule calendar does not cover every requested calendar date")
    scheduled_slates = {
        day: {"gameCount": len(row["games"]), "games": row["games"]}
        for day, row in official_schedule_by_date.items() if row["games"]
    }
    verified_off_days = sorted(
        day for day, row in official_schedule_by_date.items() if row["verifiedOffDay"])
    source = sqlite3.connect(f"file:{RAW_DB.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        slates = {}
        for offset in range((end - start).days + 1):
            day = (start.fromordinal(start.toordinal() + offset)).isoformat()
            bundle = build_day(source, day, args.output, official_schedule_by_date[day])
            if bundle:
                slates[day] = bundle
    finally:
        source.close()
    missing_scheduled = sorted(set(scheduled_slates) - set(slates))
    manifest = {"start": start.isoformat(), "end": end.isoformat(),
                "officialSchedule": official_schedule_by_date,
                "scheduledDates": sorted(scheduled_slates),
                "verifiedOffDays": verified_off_days,
                "scheduledSlates": scheduled_slates,
                "slates": slates,
                "archiveCoverage": {
                    "officialScheduleSource": official_calendar.get("source"),
                    "scheduledSlateCount": len(scheduled_slates),
                    "scheduledGameCount": sum(x["gameCount"] for x in scheduled_slates.values()),
                    "bundledDates": sorted(slates),
                    "missingScheduledDates": missing_scheduled,
                    "missingDatesAreNotAssumedOffDays": True,
                    "source": "state/true_blender.sqlite.gz"
                }}
    path = args.output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(path),
                      "scheduledSlateCount": len(scheduled_slates),
                      "scheduledGameCount": sum(x["gameCount"] for x in scheduled_slates.values()),
                      "verifiedOffDays": verified_off_days,
                      "bundledDates": sorted(slates),
                      "missingScheduledDates": missing_scheduled}, indent=2))


if __name__ == "__main__":
    main()
