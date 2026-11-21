#!/usr/bin/env python3
"""Dispatch the next confirmed Blender cycle only while official games remain pregame.

This is a continuation handoff, not a selector or a gate. It reads the already
saved per-game start times, honors each game's puck-drop freeze, and avoids
starting a duplicate workflow when another engine run is queued or active.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_STATUSES = {"queued", "inProgress", "waiting", "requested"}


def load_slate() -> tuple[str, dict]:
    requested = (os.getenv("BLENDER_EXECUTED_DATE")
                 or os.getenv("REQUESTED_DATE") or "").strip()
    folder = Path("state/site_runs")
    candidates = []
    if requested:
        path = folder / f"{requested}.json"
        candidates = [path] if path.is_file() else []
    else:
        candidates = sorted(
            (p for p in folder.glob("*.json")
             if len(p.stem) == 10 and p.stem[4] == "-" and p.stem[7] == "-"),
            reverse=True,
        )
    states = []
    for path in candidates:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (isinstance(state, dict) and state.get("slateDate")
                and isinstance(state.get("gameSurvivorPool"), list)):
            states.append((str(state["slateDate"]), state))
    if not states:
        raise RuntimeError("No saved authoritative slate state with game start receipts")
    return max(states, key=lambda item: (
        item[0], str(item[1].get("updatedUTC") or "")
    ))


def upcoming_games(state: dict, now: datetime) -> list[dict]:
    upcoming = []
    for game in state.get("gameSurvivorPool", []):
        raw = game.get("gameStartUTC")
        if not raw:
            continue
        try:
            start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if start.tzinfo and start.astimezone(timezone.utc) > now:
            upcoming.append(game)
    return upcoming


def main() -> int:
    repository = os.environ["GITHUB_REPOSITORY"]
    current_run = str(os.getenv("GITHUB_RUN_ID") or "")
    slate_date, state = load_slate()
    future = upcoming_games(state, datetime.now(timezone.utc))
    if not future:
        print("BLENDER_CONTINUATION: no future game starts remain; puck-drop freeze reached",
              flush=True)
        return 0

    result = subprocess.run(
        ["gh", "run", "list", "--repo", repository,
         "--workflow", "nhl-true-blender.yml",
         "--json", "databaseId,status", "--limit", "50"],
        check=True, capture_output=True, text=True,
    )
    runs = json.loads(result.stdout or "[]")
    other_active = [
        run for run in runs
        if str(run.get("databaseId") or "") != current_run
        and run.get("status") in ACTIVE_STATUSES
    ]
    if other_active:
        print("BLENDER_CONTINUATION: another engine run is already queued/active; "
              "not creating a duplicate", flush=True)
        return 0

    game_ids = [str(game.get("gameId") or "") for game in future]
    print("BLENDER_CONTINUATION: dispatching next confirmed source cycle; "
          f"slate={slate_date}; futureGames={len(future)}; gameIds={game_ids}",
          flush=True)
    subprocess.run(
        ["gh", "workflow", "run", "nhl-true-blender.yml",
         "--repo", repository, "--ref", "main",
         "--field", f"date={slate_date}", "--field", "mode=confirmed"],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
