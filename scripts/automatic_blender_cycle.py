"""Choose and execute the NHL Blender's complete autonomous slate lifecycle.

A fixed local clock cannot say when a particular NHL game has reached puck drop.
Use the official slate instead: a future game must keep receiving original G0-G18
research, even if other games on the same slate already started. Never select
or replace an original Core here; the engine/storage own those decisions.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
from datetime import date as Date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from nhl_true_blender_engine.sources import NHLClient

ET = ZoneInfo("America/New_York")
VALID_MODES = frozenset({"projected", "confirmed", "watch", "grade"})


def choose_mode(games, now, *, date=None):
    """Choose engine phase from official start times, never a static 7 PM cutoff.

    Projected scouting starts early; use confirmed collection within three
    hours of the first start, or whenever a game already started and other
    games remain pre-puck. A game that already started is excluded by the
    original engine, not reauthorized by this scheduling helper.
    """
    if now.tzinfo is None:
        raise ValueError("Official phase clock must include a timezone")
    slate_day = Date.fromisoformat(date) if date else now.astimezone(ET).date()
    if slate_day > now.astimezone(ET).date():
        raise ValueError("Scheduled automatic runs cannot target a future day")
    if slate_day < now.astimezone(ET).date():
        return "grade"
    # Never suppress the new Eastern calendar day's pregame research merely
    # because it is before 08:00. Frozen prior-day cards are graded through
    # pending_recent_grades after this slate's own research.
    starts = []
    for game in games:
        raw = game.get("startTimeUTC") or game.get("startUTC")
        if not raw:
            raise ValueError("Official scheduled game has no puck-drop timestamp")
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if start.tzinfo is None:
            raise ValueError("Puck-drop timestamp must be timezone aware")
        starts.append(start.astimezone(timezone.utc))
    now_utc = now.astimezone(timezone.utc)
    future = [start for start in starts if now_utc < start]
    if not future:
        return "grade"  # the grade runner waits for official NHL final results
    if min(starts) <= now_utc or min(future) - now_utc <= timedelta(hours=3):
        return "confirmed"
    return "projected"


async def official_games(day):
    client = NHLClient()
    try:
        response = await client.score(day)
    finally:
        await client.close()
    games = response.get("data", {}).get("games")
    if not isinstance(games, list):
        raise RuntimeError("Official NHL schedule omitted games; refusing to guess phase")
    return games


def pending_recent_grades(root, day):
    """Retry every ungraded frozen Core from the current NHL season.

    A seven-day window silently abandoned older cards after an outage.
    Keep the old G18 card immutable; grade at most two per automatic cycle.
    The original frozen Core is never replaced. Only slates which actually
    have a saved card are retried; an off day or NO_CORE is not graded as a win.
    """
    db = Path(root) / "true_blender.sqlite"
    slate_day = Date.fromisoformat(day)
    season_start = Date(slate_day.year if slate_day.month >= 9 else slate_day.year - 1, 9, 1)
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute(
            "SELECT slate_date FROM cards WHERE slate_date >= ? AND slate_date <= ? "
            "AND (grade IS NULL OR grade = '') ORDER BY slate_date",
            (season_start.isoformat(), day),
        ).fetchall()
        # Bound per-run replay cost; scheduled runs drain older ungraded cards.
        return [row[0] for row in rows[:2]]
    finally:
        con.close()


def bootstrap_projected_before_confirmed(day, games, now, *, root="state"):
    """Run original PROJECTED source gates before the first confirmed refresh.

    A CONFIRMED phase may legitimately lack official pre-puck dressed
    rosterSpots or coach-confirmed EV lines. That does NOT allow projecting
    confirmed statuses, and must not cause the engine to miss its earlier
    source-labelled projected card entirely. Run the original engine on
    separate PROJECTED receipts *once*, only while every scheduled game is
    still pre-puck and no authoritative slate card exists. The following
    CONFIRMED run still requires its own actual confirmation evidence.
    """
    if not games:
        return False
    now_utc=now.astimezone(timezone.utc)
    for game in games:
        raw=game.get("startTimeUTC") or game.get("startUTC")
        if not raw:
            return False
        start=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
        if start.tzinfo is None or start.astimezone(timezone.utc)<=now_utc:
            return False
    db=Path(root)/"true_blender.sqlite"
    if db.is_file():
        con=sqlite3.connect(str(db))
        try:
            existing=con.execute(
                "SELECT 1 FROM cards WHERE slate_date=? LIMIT 1",(day,)).fetchone()
        except sqlite3.OperationalError as exc:
            # A corrupt/unmigrated ledger must be repaired, not treated as
            # evidence that the slate's saved Core is absent.
            raise RuntimeError("Cannot inspect authoritative saved Core ledger") from exc
        finally:
            con.close()
        if existing:
            return False
    print(f"PRE-GAME ORIGINAL PROJECTED PASS BEFORE CONFIRMED: {day}",flush=True)
    subprocess.run(
        ["python","run_true_blender.py","--date",day,"--mode","projected"],
        check=True)
    return True


def execute_commands(day, mode, *, root="state"):
    """Execute official research and auditable postgame operations, never picks."""
    if mode in ("projected", "confirmed"):
        subprocess.run(["python", "run_true_blender.py", "--date", day,
                        "--mode", mode], check=True)
    else:
        subprocess.run(["python", "-m", "scripts.run_cycle", "--date", day,
                        "--mode", mode], check=True)
    if mode != "watch":
        for other in pending_recent_grades(root, day):
            if other == day and mode == "grade":
                continue  # already tried as the primary phase
            # No result is invented if those games are not yet final.
            subprocess.run(["python", "-m", "scripts.run_cycle", "--date", other,
                            "--mode", "grade"], check=True)


def main():
    now = datetime.now(ET)
    manual_date = os.getenv("REQUESTED_DATE", "").strip()
    manual_mode = os.getenv("REQUESTED_MODE", "").strip().lower()
    if manual_mode and manual_mode not in VALID_MODES:
        raise SystemExit("Unsupported Blender phase: " + manual_mode)
    if manual_date:
        day = Date.fromisoformat(manual_date).isoformat()
    else:
        # Midnight ET starts the NEW slate's projected research. Prior-day
        # grading runs independently against already-frozen Cards.
        day = now.date().isoformat()
    # Manual runs have an explicit phase. Otherwise the official NHL schedule
    # is authoritative for projected/confirmed/grade lifecycle transitions.
    games = asyncio.run(official_games(day)) if not manual_mode else None
    mode = manual_mode or choose_mode(games, now, date=day)
    github_env = os.getenv("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as env:
            env.write(f"BLENDER_EXECUTED_DATE={day}\nBLENDER_EXECUTED_MODE={mode}\n")
    if mode in ("projected", "confirmed") and os.getenv("MONEYPUCK_CSV_DIR"):
        os.environ["MONEYPUCK_EXPORT_ASOF"] = day
    print(f"BLENDER AUTOMATIC {day} {mode} {now.isoformat()} ET", flush=True)
    if mode == "confirmed" and not manual_mode:
        bootstrap_projected_before_confirmed(day,games,now)
    execute_commands(day, mode)


if __name__ == "__main__":
    main()
