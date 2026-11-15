"""Standalone GitHub Actions entrypoint for the integrated G0–G18 engine.

Uses official NHL schedule/rosters and previously sourced evidence in persistent
SQLite. Missing independent goalie/line/route evidence is reported, not invented.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from nhl_true_blender_engine.sources import NHLClient, official_slate
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.secondary_sources import collect_secondary
from nhl_true_blender_engine.lineup_parser import ingest_lineups
from nhl_true_blender_engine.historical_shots import collect_history
from nhl_true_blender_engine.moneypuck_import import import_moneypuck
from nhl_true_blender_engine.scouting_import import ingest_scouting
from nhl_true_blender_engine.goal_tracking import collect_goal_sprites
import httpx
from datetime import timezone
from nhl_true_blender_engine.engine import execute, MASTER, OVERLAY
from nhl_true_blender_engine.storage import open_db

async def run(date, stage, state_dir="state", output_dir="runs"):
    state = Path(state_dir)
    output = Path(output_dir)
    state.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    con = open_db(str(state / "true_blender.sqlite"))
    try:
        async with _Client() as client:
            snapshot = await official_slate(client, date, con)
            historical = await collect_history(client, con, snapshot, date, stage)
            goal_tracking = {'status': 'DISABLED_BY_DEFAULT', 'reason': 'Historical sprite archive is supplemental, not G0 anatomical evidence'}
            if os.environ.get('ENABLE_GOAL_SPRITES') == '1':
                goal_tracking = await collect_goal_sprites(client, snapshot, date, max_goals=12)
        source_research = await collect_secondary(con, snapshot, date, stage)
        try:
            async with httpx.AsyncClient(timeout=18) as http:
                response = await http.get("https://www.betweenthelineshockey.com/tonight.md")
                response.raise_for_status()
                if f"games dated {date}" not in response.text.splitlines()[0]:
                    raise ValueError("Lineup source slate date mismatch")
                observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
                source_research["parsedLineups"] = ingest_lineups(con, snapshot, date, stage, response.text, observed)
        except (httpx.HTTPError, ValueError) as exc:
            source_research["lineupParseError"] = str(exc)
        csv_dir = os.environ.get('MONEYPUCK_CSV_DIR')
        if csv_dir and Path(csv_dir, 'skaters.csv').exists():
            source_research['moneypuck'] = import_moneypuck(
                con, snapshot, date, stage, csv_dir,
                os.environ.get('MONEYPUCK_EXPORT_ASOF'))
        # Starter evidence is attached first; anatomical scouting must never invent a starter.
        attach(con, snapshot, date, stage)
        scouting_path = os.environ.get('GOALIE_SCOUTING_JSON')
        if scouting_path:
            source_research['goalieScouting'] = ingest_scouting(
                con, snapshot, date, stage, scouting_path)
            attach(con, snapshot, date, stage)
        result = execute(con, snapshot, date, stage)
        summary = {k: v for k, v in result.items() if k != "scan"}
        summary.update({
            "officialSource": snapshot.get("officialSource"),
            "secondarySourceResearch": source_research,
            "historicalShotResearch": historical,
            "historicalGoalTracking": goal_tracking,
            "collectionErrors": snapshot.get("collectionErrors", []),
            "masterGateOrder": MASTER,
            "overlayGateOrder": OVERLAY,
            "fullSelectionEngine": "nhl_true_blender_engine.engine.execute",
            "validatedCorePublished": bool(result.get("card")),
        })
        path = output / f"true_blender_{date}_{stage.lower()}.json"
        path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        print(json.dumps({
            "output": str(path), "games": result["games"],
            "eligibleSkaters": result["eligibleSkaterRows"],
            "gateRows": result["gateRows"],
            "g0Complete": result["g0Complete"],
            "g0Directions": result["g0Directions"],
            "missingByGate": result["missingByGate"],
            "corePublished": bool(result.get("card")),
            "errors": result["errors"][:10],
        }, indent=2))
        return summary
    finally:
        con.close()

class _Client:
    async def __aenter__(self):
        self.client = NHLClient()
        return self.client
    async def __aexit__(self, *args):
        await self.client.close()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date")
    p.add_argument("--mode", choices=["projected", "confirmed"], default="projected")
    args = p.parse_args()
    date = args.date or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    datetime.strptime(date, "%Y-%m-%d")
    asyncio.run(run(date, args.mode.upper()))

if __name__ == "__main__":
    main()
