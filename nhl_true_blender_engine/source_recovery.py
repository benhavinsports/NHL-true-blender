"""Scope source retries to incomplete pregame games; never choose recipients."""
from collections import defaultdict
from datetime import datetime, timezone
from .engine import MASTER
from .storage import game_started

def recovery_snapshot(con, snapshot, date, stage, result, now=None):
    now=now or datetime.now(timezone.utc)
    selected=result.get('g0TwoGoalieDirectionDecisions') or {}
    by_player=defaultdict(dict)
    for row in con.execute('SELECT game_id,player_id,gate,disposition FROM gates '
                           'WHERE slate_date=? AND stage=?',(date,stage)):
        by_player[(str(row['game_id']),str(row['player_id']))][row['gate']]=row['disposition']
    missing=set()
    for (gid,pid),rows in by_player.items():
        if pid.startswith(('GOALIE_DIRECTION:','G0_RESEARCH:')):
            continue
        # An actual original-gate elimination is not a network error and
        # cannot be reopened merely by rerunning optional diagnostics.
        if 'ELIMINATED' in rows.values():
            continue
        for gate in MASTER[:-1]:
            if rows.get(gate)!='PASS':
                if rows.get(gate) in (None,'NOT_EXECUTED'):
                    missing.add(gid)
                break
    games=[g for g in snapshot.get('games',[]) if not game_started(g,now) and
           (str(g['id']) not in selected or str(g['id']) in missing)]
    return {**snapshot,'games':games}
