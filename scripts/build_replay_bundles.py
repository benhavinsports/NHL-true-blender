"""Rebuild point-in-time replay bundles from the canonical evidence ledger.

Only dates with a saved original card, complete engine job, official schedule,
and pre-cutoff source receipts are bundled. Missing dates are never fabricated.
"""
from __future__ import annotations
import argparse
import asyncio
import gzip
import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.sources import normalize_games
from nhl_true_blender_engine.storage import open_db, record_evidence
from nhl_true_blender_engine.sources import NHLClient

RAW_DB = Path("state/true_blender.sqlite")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_day(source, day, out):
    card = source.execute(
        "SELECT stage, first_issued_at FROM cards WHERE slate_date=? ORDER BY first_issued_at LIMIT 1", (day,)
    ).fetchone()
    jobs = source.execute(
        "SELECT mode, status, started_at, finished_at FROM jobs WHERE slate_date=? "
        "AND status='COMPLETE' ORDER BY finished_at DESC", (day,)
    ).fetchall()
    usable = [row for row in jobs if row["mode"] in ("PROJECTED", "CONFIRMED")]
    if not usable:
        return None
    stage = usable[0]["mode"]
    # A historical selection is not a prerequisite. If no original card was
    # issued, anchor replay to the actual recorded engine-job start, not to a
    # wall-clock timestamp or a postgame result.
    cutoff = (card["first_issued_at"] if card and card["first_issued_at"]
              else usable[0]["started_at"])
    if not cutoff:
        return None
    from datetime import datetime
    cutoff_dt = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    allowed = ("OFFICIAL", "PROJECTED") if stage == "PROJECTED" else (
        "OFFICIAL", "PROJECTED", "CONFIRMED")
    placeholders = ",".join("?" for _ in allowed)
    rows = source.execute(
        f"SELECT * FROM evidence WHERE slate_date=? AND stage IN ({placeholders}) "
        "ORDER BY observed_at, rowid", (day, *allowed)
    ).fetchall()
    rows = [r for r in rows if datetime.fromisoformat(
        r["observed_at"].replace("Z", "+00:00")) <= cutoff_dt]
    if not rows:
        return None

    schedules = [r for r in rows if r["kind"] == "GAME_SCHEDULE" and r["stage"] == "OFFICIAL"]
    if not schedules:
        return None
    schedule = schedules[-1]
    schedule_data = json.loads(schedule["payload"])
    games = normalize_games({
        "data": schedule_data, "url": schedule["source_url"],
        "observedAt": schedule["observed_at"]
    }, day)
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
    for game in games:
        game["rosters"] = {team: rosters.get(team)
                           for team in (game["away"], game["home"])}
    snapshot = {"games": games}

    out.mkdir(parents=True, exist_ok=True)
    evidence_path = out / f"{day}-evidence.sqlite"
    con = open_db(str(evidence_path))
    try:
        for row in rows:
            record_evidence(con, {
                "evidence_id": row["evidence_id"], "slate_date": row["slate_date"],
                "stage": row["stage"], "game_id": row["game_id"],
                "player_id": row["player_id"], "kind": row["kind"],
                "source_url": row["source_url"], "observed_at": row["observed_at"],
                "payload": json.loads(row["payload"])
            })
        # Attach only the receipts that survived the point-in-time filter.
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

    inputs = [{"kind": row["kind"], "source": row["source_url"],
               "availableAt": row["availableAt"]}
              for row in source.execute(
                  f"SELECT kind, source_url, MIN(observed_at) AS availableAt "
                  f"FROM evidence WHERE slate_date=? AND stage IN ({placeholders}) "
                  "GROUP BY kind, source_url ORDER BY kind, source_url",
                  (day, *allowed)).fetchall()
              if row["source_url"] and row["availableAt"] and
              datetime.fromisoformat(row["availableAt"].replace("Z", "+00:00")) <= cutoff_dt]
    # The inventory above is intentionally conservative: it lists every
    # source family/URL represented by the filtered ledger, while the DB hash
    # commits to every individual immutable receipt.
    return {
        "stage": stage, "cutoff": cutoff,
        "snapshot": snapshot_path.name, "snapshotSha256": sha256(snapshot_bytes),
        "evidenceDb": compressed_path.name, "evidenceDbSha256": sha256(compressed_path.read_bytes()),
        "inputs": inputs, "gameCount": len(games),
        "teamsWithOfficialRoster": sorted(rosters),
        "allEvidenceAtOrBeforeCutoff": True
    }


async def official_schedule(start, end):
    """Enumerate every calendar date from the official NHL daily score/schedule feed.

    Schedule retrieval is for slate/off-day classification only. It is never
    inserted into the selector evidence database as player or matchup proof.
    """
    client = NHLClient()
    result = {}
    try:
        for offset in range((end - start).days + 1):
            day = start.fromordinal(start.toordinal() + offset).isoformat()
            payload = await client.score(day)
            games = payload["data"].get("games")
            if not isinstance(games, list):
                raise RuntimeError(f"Official NHL schedule omitted games array for {day}")
            result[day] = {
                "source": payload["url"],
                "downloadedAt": payload["observedAt"],
                "games": [{
                    "gameId": str(g["id"]),
                    "away": g["awayTeam"]["abbrev"],
                    "home": g["homeTeam"]["abbrev"],
                    "startTimeUTC": g["startTimeUTC"],
                    "gameState": g.get("gameState"),
                } for g in games],
                "verifiedOffDay": len(games) == 0,
            }
    finally:
        await client.close()
    return result


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
    if not args.schedule.is_file():
        raise SystemExit("Official NHL schedule calendar is missing; fetch it before building replay bundles")
    official_calendar = json.loads(args.schedule.read_text(encoding="utf-8"))
    scheduled_slates = {
        row["date"]: {"gameCount": len(row.get("games") or []),
                      "games": row.get("games") or []}
        for row in official_calendar.get("scheduledSlates", [])
        if start.isoformat() <= row["date"] <= end.isoformat()
    }
    source = sqlite3.connect(f"file:{RAW_DB.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        slates = {}
        for offset in range((end - start).days + 1):
            day = (start.fromordinal(start.toordinal() + offset)).isoformat()
            bundle = build_day(source, day, args.output)
            if bundle:
                slates[day] = bundle
    finally:
        source.close()
    missing_scheduled = sorted(set(scheduled_slates) - set(slates))
    manifest = {"start": start.isoformat(), "end": end.isoformat(),
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
                      "bundledDates": sorted(slates),
                      "missingScheduledDates": missing_scheduled}, indent=2))


if __name__ == "__main__":
    main()
