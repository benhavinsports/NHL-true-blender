"""Compatibility CLI: one authoritative NHL True Blender selection engine.

Legacy callers may still invoke run_daily.py, but it must never run the
separate root-level engine.run_slate / gate_executor / core_publication
selection pipeline. The integrated collector and G0..G18 engine own every
selection, saved card, and site export.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from run_true_blender import run


def main():
    parser = argparse.ArgumentParser(description="Run the canonical NHL True Blender")
    parser.add_argument("--date", default=None)
    parser.add_argument("--mode", choices=("projected", "confirmed"), default="projected")
    parser.add_argument("--history", type=int, default=8,
                        help="Legacy CLI compatibility; no alternate selection logic")
    parser.add_argument("--out", default="runs")
    args = parser.parse_args()
    date = args.date or datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    datetime.strptime(date, "%Y-%m-%d")
    asyncio.run(run(date, args.mode.upper(), output_dir=args.out))


if __name__ == "__main__":
    main()
