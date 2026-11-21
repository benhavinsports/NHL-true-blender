"""Continue pregame source research for every unresolved original gate.

This module only schedules further collection. It never selects, eliminates,
certifies, replaces, or assigns a Core recipient. A genuine ELIMINATED verdict
is preserved, but cannot prevent independent missing evidence from being
researched in the same matchup.
"""
from collections import defaultdict
from datetime import datetime, timezone
from .engine import MASTER
from .storage import game_started


def recovery_snapshot(con, snapshot, date, stage, result, now=None):
    now = now or datetime.now(timezone.utc)
    selected = result.get('g0TwoGoalieDirectionDecisions') or {}
    by_player = defaultdict(dict)
    for row in con.execute(
        'SELECT game_id,player_id,gate,disposition FROM gates '
        'WHERE slate_date=? AND stage=?', (date, stage)
    ):
        by_player[(str(row['game_id']), str(row['player_id']))][row['gate']] = row['disposition']

    researched_games = set()
    still_need_sources = set()
    for (gid, pid), rows in by_player.items():
        if pid.startswith(('GOALIE_DIRECTION:', 'G0_RESEARCH:')):
            continue
        researched_games.add(gid)
        # Follow the ORIGINAL gate order and recover only the FIRST
        # nonpassing decision for this player. A gate after an ELIMINATED
        # earlier gate is correctly NOT_EXECUTED; it is not a missing source
        # and must never send the whole matchup back through collection.
        # Other players in this same game are still checked independently.
        first = next((gate for gate in MASTER[:-1]
                      if rows.get(gate) != 'PASS'), None)
        if first is not None and rows.get(first) in (None, 'NOT_EXECUTED'):
            still_need_sources.add(gid)

    for game in snapshot.get('games', []):
        gid = str(game['id'])
        # No G0 direction or no player matrix is itself a reason to keep
        # researching sources, even when there are zero scanned skaters.
        if gid not in selected or gid not in researched_games:
            still_need_sources.add(gid)

    games = [game for game in snapshot.get('games', [])
             if str(game['id']) in still_need_sources and
             not game_started(game, now)]
    return {**snapshot, 'games': games}
