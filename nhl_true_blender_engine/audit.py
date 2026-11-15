"""Source-preserving miss audit. A bad outcome alone is not proof of an erroneous gate."""
import json
from .storage import stamp, transaction, encode, get_card
from .engine import GATE_PATCHES


def configure_audit_table(con):
    con.execute('''CREATE TABLE IF NOT EXISTS miss_audits (
        slate_date TEXT NOT NULL, game_id TEXT NOT NULL, player_id TEXT NOT NULL,
        card_id TEXT NOT NULL, conclusion TEXT NOT NULL, earliest_gate TEXT,
        patch_ids TEXT NOT NULL, source_comparison TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(slate_date,game_id,player_id)
    )''')


def audit_misses(con, date):
    configure_audit_table(con)
    card=get_card(con,date)
    if not card or not card['grade']:return []
    grade=con.execute('SELECT legs FROM grades WHERE card_id=?',(card['card_id'],)).fetchone()
    if not grade:return []
    result=[]
    for leg in json.loads(grade['legs']):
        if leg['result']=='HIT':continue
        game_id=str(leg['gameId']);pid=str(leg['playerId'])
        rows=con.execute('''SELECT gate,disposition,details,stage FROM gates
                              WHERE slate_date=? AND game_id=? AND player_id=?
                              AND gate LIKE 'G%' ORDER BY evaluated_at ASC''',
                           (date,game_id,pid)).fetchall()
        # Earliest actual, source-supported missing/failed gate in the stored pregame record.
        # Never create a retrospective gate verdict or select the player who did score.
        gate_order={**{f'G{i}':i for i in range(19)},'G10.5':10.5}
        incomplete=sorted((r for r in rows if r['disposition'] in ('ELIMINATED','NOT_EXECUTED')),
                          key=lambda r:gate_order.get(r['gate'],100))
        earliest=incomplete[0]['gate'] if incomplete else None
        conclusion=('PREGAME_GATE_RECEIPT_INCOMPLETE' if earliest else
                    'MISS_WITHOUT_PROVEN_PREGAME_GATE_DEFECT')
        patches=GATE_PATCHES.get(earliest,[]) if earliest else []
        detail={'preGameGateRows':len(rows),'firstDefect':earliest,
                'finding':'Missing historical gate receipt is not a reason to retroactively switch picks.',
                'officialGoalCount':0,
                'provenPatchApplication':False}
        with transaction(con):
            con.execute('''INSERT OR IGNORE INTO miss_audits VALUES (?,?,?,?,?,?,?,?,?)''',
                        (date,game_id,pid,card['card_id'],conclusion,earliest,
                         encode(patches),encode(detail),stamp()))
        result.append({'player':leg['player'],'gameId':game_id,'earliestGate':earliest,
                       'patchesToAudit':patches,'conclusion':conclusion})
    return result