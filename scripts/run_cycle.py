"""Free GitHub Actions scheduled change-watch and official postgame cycle."""
import argparse
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from nhl_true_blender_engine.audit import audit_misses
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.secondary_sources import collect_secondary
from nhl_true_blender_engine.sources import NHLClient, official_slate, collect_watch, official_final_grade
from nhl_true_blender_engine.storage import open_db, get_card
from scripts.publish_site_state import PublicationConflict, _write

ET = ZoneInfo('America/New_York')

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
            attach(con,slate,date,'CONFIRMED')
            watch=await collect_watch(None,con,date,slate)
            output={'slateDate':date,'mode':mode,'status':'PREGAME_CHANGE_WATCH',
                    'gameCount':len(slate['games']),**watch}
        elif mode=='grade':
            card=get_card(con,date)
            if not card:
                output={'slateDate':date,'mode':mode,'status':'NO_ORIGINAL_CORE_TO_GRADE'}
            elif card.get('grade'):
                output={'slateDate':date,'mode':mode,'status':'ALREADY_OFFICIALLY_GRADED',
                        'cardId':card['card_id'],'grade':card['grade']}
            else:
                nhl=NHLClient()
                try:
                    official=await official_final_grade(nhl,con,date)
                finally:
                    await nhl.close()
                if not official.get('grade'):
                    output={'slateDate':date,'mode':mode,'status':official.get('status','WAITING_FOR_FINAL')}
                else:
                    audits=audit_misses(con,date)
                    grade=official['grade']
                    output={'slateDate':date,'mode':mode,'status':'GRADED_OFFICIAL_GOAL_EVENTS',
                        'cardId':grade['card_id'],'grade':grade,'missAudits':audits}
                    card_path=root/'site_cards'/f'{date}.json'
                    if card_path.exists():
                        prior=json.loads(card_path.read_text(encoding='utf-8'))
                        if prior.get('cardId')!=grade['card_id']:
                            raise PublicationConflict('Official grade card ID conflicts with published site card')
                        if prior.get('gradeJson'):
                            old=json.loads(prior['gradeJson'])
                            if old and old.get('result')!=grade['result']:
                                raise PublicationConflict('Previously verified grade conflict')
                        prior['gradeJson']=json.dumps({
                            'hits':sum(x['result']=='HIT' for x in grade['legs']),
                            'legs':len(grade['legs']),
                            'result':grade['result'],
                            'officialSources':grade['official_sources']})
                        prior['status']='FROZEN_GRADED'
                        _write(card_path,prior)
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
