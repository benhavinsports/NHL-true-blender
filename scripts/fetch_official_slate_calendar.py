"""Fetch the official NHL schedule calendar for a historical replay window."""
from __future__ import annotations
import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import httpx

ROOT = "https://api-web.nhle.com/v1/schedule/"


def fetch_calendar(start: date, end: date):
    client = httpx.Client(timeout=30, headers={"User-Agent": "NHL-True-Blender-Historical-Audit/1.0"})
    cursor = start
    weeks = []
    seen = set()
    try:
        while cursor <= end:
            response = client.get(ROOT + cursor.isoformat())
            response.raise_for_status()
            payload = response.json()
            downloaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            game_week = payload.get("gameWeek")
            if not isinstance(game_week, list):
                raise ValueError(f"Official NHL schedule omitted gameWeek for {cursor}")
            for day in game_week:
                day_text = day.get("date")
                if not day_text:
                    raise ValueError("Official NHL schedule day missing date")
                day_date = date.fromisoformat(day_text)
                if not start <= day_date <= end or day_text in seen:
                    continue
                seen.add(day_text)
                games = []
                for game in day.get("games") or []:
                    away = (game.get("awayTeam") or {}).get("abbrev")
                    home = (game.get("homeTeam") or {}).get("abbrev")
                    game_id = game.get("id")
                    start_utc = game.get("startTimeUTC")
                    if game_id is None or not away or not home or not start_utc:
                        raise ValueError(f"Official NHL schedule game missing ID/teams/start: {day_text}")
                    # Canonical replay consumers use id + startTimeUTC. Keep the
                    # NHL API aliases as well for older collectors, but never emit
                    # a schedule row that lacks the fields required for cutoff math.
                    games.append({"id": str(game_id), "gameId": str(game_id),
                                  "away": away, "home": home,
                                  "startTimeUTC": start_utc, "startUTC": start_utc,
                                  "gameState": game.get("gameState") or "UNKNOWN"})
                weeks.append({"date": day_text, "games": games,
                              "officialSourceUrl": response.url.__str__(),
                              "downloadedAt": downloaded_at,
                              "schedulePublicationTime": "OFFICIAL_SCHEDULE_PUBLISHED_2026-07-16"})
            next_start = payload.get("nextStartDate")
            if not next_start:
                cursor += timedelta(days=7)
            else:
                next_date = date.fromisoformat(next_start)
                if next_date <= cursor:
                    raise ValueError("Official NHL schedule nextStartDate did not advance")
                cursor = next_date
    finally:
        client.close()
    weeks.sort(key=lambda x: x["date"])
    scheduled = [x for x in weeks if x["games"]]
    return {"source": "OFFICIAL_NHL_SCHEDULE_API", "sourceRoot": ROOT,
            "start": start.isoformat(), "end": end.isoformat(),
            "calendarDays": weeks, "scheduledSlates": scheduled,
            "scheduledSlateDates": [x["date"] for x in scheduled],
            "scheduledGameCount": sum(len(x["games"]) for x in scheduled)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if end < start:
        p.error("--end must not precede --start")
    result = fetch_calendar(start, end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output),
                      "scheduledSlateCount": len(result["scheduledSlates"]),
                      "scheduledGameCount": result["scheduledGameCount"],
                      "scheduledSlateDates": result["scheduledSlateDates"]}, indent=2))


if __name__ == "__main__":
    main()
