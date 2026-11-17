"""Compatibility entrypoint: the integrated True Blender is the only selector.

Historically this script invoked the legacy root engine.py, independently
built a Core, and wrote state/authoritative_core_*.json. That could conflict
with the canonical SQLite-backed nhl_true_blender_engine run and site card.
Retain the old CLI, but delegate all decisions and persistence to the single
integrated entrypoint. No legacy selection or publication occurs here.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(
        ZoneInfo("America/New_York")).date().isoformat())
    parser.add_argument("--mode", choices=("projected", "confirmed"),
                        default="projected")
    # Accepted for compatibility; the integrated collector owns history
    # and output locations, so neither option changes selection logic.
    parser.add_argument("--history", type=int, default=8)
    parser.add_argument("--out", default="runs")
    args = parser.parse_args()

    runner = Path(__file__).resolve().with_name("run_true_blender.py")
    subprocess.run(
        [sys.executable, str(runner), "--date", args.date,
         "--mode", args.mode],
        check=True,
    )


if __name__ == "__main__":
    main()
