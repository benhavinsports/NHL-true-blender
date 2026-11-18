"""Import source-validated Daily Faceoff historical starter observations into Blender's canonical evidence ledger.

Only a dated report timestamp at/before the slate cutoff, an official schedule matchup,
a unique NHL goalie identity, and a matching team image identity are eligible. Page
download time is provenance only and is never treated as historical availability time.
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nhl_true_blender_engine.storage import open_db, record_evidence

RAW_DB = Path("state/true_blender.sqlite")
SOURCE = "https://www.dailyfaceoff.com/starting-goalies/"


def parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def evidence_id(day, game_id, team, goalie_id, report_at):
    raw = "|".join((day, str(game_id), team, str(goalie_id), report_at))
    return "dfo-historical-goalie-" + hashlib.sha256(raw.encode()).hexdigest()[:28]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("goalie_archive", type=Path)
    args = p.parse_args()
    if not RAW_DB.is_file():
        raise SystemExit("Canonical evidence database missing; restore it before ingestion")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    archive = json.loads(args.goalie_archive.read_text(encoding="utf-8"))
    schedule = manifest.get("officialSchedule") or {}
    imported, rejected = [], []
    con = open_db(str(RAW_DB))
    try:
        for page in archive.get("pages", []):
            day = page.get("date")
            schedule_row = schedule.get(day) or {}
            games = schedule_row.get("games") or []
            if not games:
                continue
            starts = [parse_utc(g.get("startTimeUTC")) for g in games]
            if any(x is None for x in starts):
                rejected.append({"date": day, "reason": "OFFICIAL_GAME_START_MISSING"})
                continue
            cutoff = min(starts) - timedelta(minutes=5)
            page_url = page.get("url") or SOURCE + str(day)
            if page.get("httpStatus") != 200:
                rejected.append({"date": day, "reason": "DATED_PAGE_UNAVAILABLE"})
                continue
            for game in page.get("games", []):
                if game.get("officialScheduleMatch") is not True:
                    rejected.append({"date": day, "matchup": [game.get("away"), game.get("home")],
                                     "reason": "MATCHUP_NOT_MATCHED_TO_OFFICIAL_SCHEDULE"})
                    continue
                official = next((g for g in games
                                 if g.get("away") == game.get("away")
                                 and g.get("home") == game.get("home")), None)
                if not official:
                    rejected.append({"date": day, "reason": "OFFICIAL_MATCHUP_NOT_FOUND"})
                    continue
                game_id = str(official.get("id") or official.get("gameId"))
                for side, team in (("awayGoalie", game.get("away")), ("homeGoalie", game.get("home"))):
                    goalie = game.get(side)
                    if not goalie:
                        rejected.append({"date": day, "gameId": game_id, "team": team,
                                         "reason": "GOALIE_CARD_MISSING"})
                        continue
                    report_at = goalie.get("reportUpdatedAt")
                    report_dt = parse_utc(report_at)
                    identity = goalie.get("nhlIdentityResolution") or {}
                    player_id = identity.get("playerId")
                    if not report_dt or report_dt > cutoff:
                        rejected.append({"date": day, "gameId": game_id, "team": team,
                                         "goalie": goalie.get("name"),
                                         "reason": "REPORT_TIME_MISSING_OR_AFTER_PREGAME_CUTOFF"})
                        continue
                    if identity.get("status") != "EXACT_OFFICIAL_NHL_NAME_AND_GOALIE_MATCH" or not player_id:
                        rejected.append({"date": day, "gameId": game_id, "team": team,
                                         "goalie": goalie.get("name"),
                                         "reason": "NO_UNIQUE_OFFICIAL_NHL_GOALIE_ID"})
                        continue
                    if goalie.get("imageTeamAbbrevMatchesAssignedTeam") is not True:
                        rejected.append({"date": day, "gameId": game_id, "team": team,
                                         "goalie": goalie.get("name"),
                                         "reason": "IMAGE_TEAM_IDENTITY_NOT_VERIFIED"})
                        continue
                    status_text = goalie.get("status")
                    status = "CONFIRMED" if status_text == "Confirmed" else "EXPECTED"
                    stage = "CONFIRMED" if status == "CONFIRMED" else "PROJECTED"
                    observed_at = report_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
                    payload = {
                        "goalieId": str(player_id), "team": team, "status": status,
                        "sourceStatus": status_text, "sourceName": goalie.get("name"),
                        "sourceReportDate": day, "reportUpdatedAt": observed_at,
                        "datedEyewitnessMorningSkateFirstOff": False,
                        "historicalArchive": True,
                        "identityResolution": identity,
                        "teamIdentityVerifiedByImage": True,
                        "officialGameId": game_id,
                        "sourcePageSha256": page.get("pageSha256"),
                        "sourcePageUrl": page_url,
                        "timeBasis": "SOURCE_REPORT_UPDATE_TIMESTAMP",
                        "downloadTimeNotUsedAsAvailabilityTime": True
                    }
                    item = {
                        "evidence_id": evidence_id(day, game_id, team, player_id, observed_at),
                        "slate_date": day, "stage": stage,
                        "game_id": game_id, "player_id": str(player_id),
                        "kind": "GOALIE_STARTER", "source_url": page_url,
                        "observed_at": observed_at, "payload": payload
                    }
                    try:
                        was_new = record_evidence(con, item)
                        imported.append({"date": day, "gameId": game_id, "team": team,
                                         "goalieId": str(player_id), "stage": stage,
                                         "evidenceId": item["evidence_id"], "inserted": was_new})
                    except (ValueError, sqlite3.IntegrityError) as exc:
                        rejected.append({"date": day, "gameId": game_id, "team": team,
                                         "reason": "IMMUTABLE_RECEIPT_CONFLICT", "detail": str(exc)})
    finally:
        con.close()
    report = {
        "source": "Daily Faceoff dated historical goalie reports",
        "importedReceiptCount": len(imported),
        "newReceiptCount": sum(x["inserted"] for x in imported),
        "rejectedCount": len(rejected),
        "imported": imported,
        "rejected": rejected,
        "selectorIntegration": "CANONICAL_EVIDENCE_LEDGER_GOALIE_STARTER",
        "downloadTimestampUsedAsAvailabilityTime": False
    }
    out = args.goalie_archive.with_name("dfo-goalie-ingestion.json")
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("imported","rejected")}, sort_keys=True))
    print(f"ingestion_report={out}")


if __name__ == "__main__":
    main()
