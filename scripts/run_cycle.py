"""Free GitHub Actions scheduled change-watch and official postgame cycle."""
import argparse
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nhl_true_blender_engine.audit import audit_misses
from nhl_true_blender_engine.postgame_recalibration import adjudicate_misses,season_history
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.secondary_sources import collect_secondary
from nhl_true_blender_engine.lineup_parser import fetch_and_ingest_lineups
from nhl_true_blender_engine.sources import NHLClient, official_slate, collect_watch, official_final_grade
from nhl_true_blender_engine.storage import open_db, get_card
from scripts.publish_site_state import PublicationConflict, _write

ET = ZoneInfo('America/New_York')

def _publish_official_grade(root,date,grade,audits,patch_adjudication=None):
    """Attach official final outcome to the SAME saved G18 card.

    Grading and missed-gate auditing never change the frozen recipient list,
    fingerprint, original path, or card revision. No unverified patch is
    represented as automatically applied.
    """
    path=root/'site_cards'/f'{date}.json'
    if not path.exists():
        raise PublicationConflict('Officially graded Core has no saved site card')
    prior=json.loads(path.read_text(encoding='utf-8'))
    if prior.get('cardId')!=grade['card_id']:
        raise PublicationConflict('Grade does not belong to the original locked Core')
    legs=json.loads(prior['legsJson'])
    graded=grade['legs']
    original={(str(l['gameId']),str(l['playerId'])) for l in legs}
    measured={(str(l['gameId']),str(l['playerId'])) for l in graded}
    if len(graded)!=len(legs) or measured!=original:
        raise PublicationConflict('Official grade players differ from original frozen card')
    hits=sum(l['result']=='HIT' for l in graded)
    outcome='WIN' if hits==len(graded) else 'LOSS'
    if outcome!=grade['result']:
        raise PublicationConflict('Official grade hit count disagrees with stored result')
    report={
        'cardId':grade['card_id'],'gradedAt':grade.get('graded_at'),
        'hits':hits,'legs':len(graded),'result':outcome,
        'playerResults':graded,
        'officialSources':grade['official_sources'],
        'missAudits':audits,
        'patchAdjudication':patch_adjudication or {},
        'patchesApplied':(patch_adjudication or {}).get('activated',[]),
        'patchStatus':('SOURCE_VALIDATED_FUTURE_GUARDS_ACTIVATED'
                       if (patch_adjudication or {}).get('activated')
                       else 'NO_CAUSALLY_PROVEN_PATCH_TRIGGER'),
        'patchesFutureSlatesOnly':True
    }
    old=json.loads(prior.get('gradeJson') or '{}')
    if old and (old.get('result')!=outcome
                or old.get('hits')!=hits or old.get('legs')!=len(graded)):
        raise PublicationConflict('Already published grade conflicts with official frozen record')
    prior['gradeJson']=json.dumps(report,sort_keys=True)
    prior['status']='FROZEN_GRADED'
    _write(path,prior)
    return report

async def execute_cycle(mode, date, root='state'):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    con=open_db(str(root/'true_blender.sqlite'))
    try:
        if mode=='watch':
            nhl=NHLClient()
            try:
                slate=await official_slate(nhl,date,con)
            finally:
                await nhl.close()
            if not slate.get('games'):
                return {'date':date,'mode':mode,'status':'NO_SCHEDULE'}
            await collect_secondary(con,slate,date,'CONFIRMED')
            lineup=await fetch_and_ingest_lineups(con,slate,date,'CONFIRMED')
            attach(con,slate,date,'WATCH')
            watch=await collect_watch(None,con,date,slate)
            output={'slateDate':date,'mode':mode,'status':'PREGAME_CHANGE_WATCH',
                    'gameCount':len(slate['games']),'lineupSource':lineup,**watch}
        elif mode=='grade':
            card=get_card(con,date)
            if not card:
                output={'slateDate':date,'mode':mode,'status':'NO_ORIGINAL_CORE_TO_GRADE'}
            else:
                # Idempotent retries still synchronize the official grade,
                # audit and frozen site card from the canonical SQLite ledger.
                grade=None
                if card.get('grade'):
                    row=con.execute('SELECT * FROM grades WHERE card_id=?',
                                    (card['card_id'],)).fetchone()
                    if not row:
                        raise PublicationConflict('Card graded but official grade receipt is missing')
                    grade=dict(row)
                    grade['legs']=json.loads(row['legs'])
                    grade['official_sources']=json.loads(row['official_sources'])
                    status='ALREADY_OFFICIALLY_GRADED'
                else:
                    nhl=NHLClient()
                    try:
                        official=await official_final_grade(nhl,con,date)
                    finally:
                        await nhl.close()
                    grade=official.get('grade')
                    status=official.get('status','WAITING_FOR_FINAL')
                if grade:
                    audits=audit_misses(con,date)
                    # A real official grade triggers automatic adjudication,
                    # not a hand-entered patch or a new Core. A missed goal
                    # alone NEVER activates a policy.
                    adjudication=adjudicate_misses(con,date)
                    season_year=int(date[:4]) if int(date[5:7])>=10 else int(date[:4])-1
                    history=season_history(con,season_year,date)
                    _write(root/'history'/f'{history["season"]}.json',history)
                    report=_publish_official_grade(root,date,grade,audits,adjudication)
                    output={'slateDate':date,'mode':mode,'status':status,
                            'cardId':grade['card_id'],'grade':report,
                            'missAudits':audits,'patchAdjudication':adjudication,
                            'seasonHistory':{
                                'season':history['season'],
                                'officiallyGradedSlates':history['officiallyGradedSlates'],
                                'wins':history['wins'],'losses':history['losses'],
                                'verifiedAutomaticGuardPatches':history['verifiedAutomaticGuardPatches'],
                                'historyPath':str(root/'history'/f'{history["season"]}.json')},
                            'originalCardPreserved':True}
                else:
                    output={'slateDate':date,'mode':mode,'status':status,
                            'originalCardPreserved':True}
        else:
            raise ValueError('run_cycle expects watch or grade')
        _write(root/'site_runs'/f'{date}-{mode}.json',output)
        print(json.dumps(output,default=str,sort_keys=True))
        return output
    finally:
        con.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mode',choices=['watch','grade'],required=True)
    p.add_argument('--date')
    a=p.parse_args()
    now=datetime.now(ET)
    date=a.date or ((now-timedelta(days=1)).date().isoformat()
                    if a.mode=='grade' and now.hour<8 else now.date().isoformat())
    asyncio.run(execute_cycle(a.mode,date))

if __name__=='__main__':main()
