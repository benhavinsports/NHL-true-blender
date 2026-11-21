"""Choose and execute the NHL Blender's complete autonomous slate lifecycle.

A fixed local clock cannot say when a particular NHL game has reached puck drop.
Use the official slate instead: a future game must keep receiving original G0-G18
research, even if other games on the same slate already started. Never select
or replace an original Core here; the engine/storage own those decisions.
"""
from __future__ import annotations

import asyncio
import json
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
    # An official NHL off-day has no starts; do not call min([]) and crash
    # the scheduled cycle before its existing pending-card processing.
    if not starts:
        return "grade"
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


def _read_grade_retry_journal(root):
    path = Path(root) / "grade_retry_journal.json"
    if not path.exists():
        return {"attempts": {}, "lastResults": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or
            not isinstance(value.get("attempts"), dict) or
            not isinstance(value.get("lastResults"), dict)):
        raise ValueError("Grade retry journal is corrupted; cannot discard history")
    return value


def _record_grade_attempt(root, slate_date, return_code, reason=None):
    """Keep evidence of failed retries without changing a frozen Core or grade."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    journal = _read_grade_retry_journal(root)
    attempts = journal["attempts"]
    attempts[slate_date] = int(attempts.get(slate_date, 0)) + 1
    journal["lastResults"][slate_date] = {
        "returnCode": return_code,
        "attemptedAtUTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reason": reason,
        "originalCoreUnchanged": True
    }
    path = root / "grade_retry_journal.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(journal, sort_keys=True, indent=2) + chr(10),
                         encoding="utf-8")
    temporary.replace(path)


def pending_recent_grades(root, day, *, include_today=True):
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
    end = day if include_today else (slate_day - timedelta(days=1)).isoformat()
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute(
            "SELECT slate_date FROM cards WHERE slate_date >= ? AND slate_date <= ? "
            "AND (grade IS NULL OR grade = '') ORDER BY slate_date",
            (season_start.isoformat(), end),
        ).fetchall()
    finally:
        con.close()
    attempts = _read_grade_retry_journal(root)["attempts"]
    # A permanently unavailable older game cannot starve every newer grade.
    # Least attempted goes first; a new card starts with zero attempts.
    return sorted((row[0] for row in rows),
                  key=lambda d: (int(attempts.get(d, 0)), d))[:2]


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
        failures = []
        # Save the current slate before reporting old grading errors.
        # A failed historical retry must never abort publishing new G0-G18
        # evidence, and it must not be silently marked successful either.
        for other in pending_recent_grades(
                root, day, include_today=(mode == "grade")):
            if other == day and mode == "grade":
                continue
            command = ["python", "-m", "scripts.run_cycle",
                       "--date", other, "--mode", "grade"]
            reason = None
            try:
                result = subprocess.run(command, check=False)
                code = result.returncode
            except OSError as exc:
                code = -1
                reason = (type(exc).__name__ + ": " + str(exc))[:300]
            _record_grade_attempt(root, other, code, reason)
            if code:
                failures.append(other + ":" + str(code))
        if failures:
            summary = ",".join(failures)
            github_env = os.getenv("GITHUB_ENV")
            if github_env:
                with open(github_env, "a", encoding="utf-8") as env:
                    env.write("BLENDER_GRADE_RETRY_FAILURES=" + summary + chr(10))
            print("::error::OFFICIAL_GRADE_RETRY_FAILED: " + summary, flush=True)


def main():
    now = datetime.now(ET)
    manual_date = os.getenv("REQUESTED_DATE", "").strip()
    manual_mode = os.getenv("REQUESTED_MODE", "").strip().lower()
    if os.getenv('TRIGGER_EVENT')=='push' and not manual_date and not manual_mode:
        # Only a change to this exact request file triggers the existing
        # production workflow. It supplies date/phase, never player names,
        # gate outcomes, replacements, scores, or another Core generator.
        request=json.loads(Path('.github/nhl-live-validation.json').read_text())
        if (not {'date','mode'}<=set(request) or
                set(request)-{'date','mode','requestId'} or request['mode']!='projected' or
                ('requestId' in request and not isinstance(request['requestId'],str))):
            raise SystemExit('Live validation request accepts only date, projected mode and an optional audit ID')
        manual_date=Date.fromisoformat(request['date']).isoformat()
        manual_mode=request['mode']
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

