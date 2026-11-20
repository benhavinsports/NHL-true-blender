import gzip
import json
import sqlite3
from datetime import datetime

from nhl_true_blender_engine.storage import open_db, record_evidence
from scripts.build_replay_bundles import build_day
from scripts.historical_pregame_clock import first_issuance_windows
from scripts import replay_historical_season as replay


def schedule():
    return {'games':[{'id':str(i),'away':'BOS','home':'NYR',
        'startTimeUTC':f'2026-10-17T{hour}:00:00Z'}
        for i,hour in enumerate(['17','23','23','23'],1)]}


def test_afternoon_start_does_not_close_three_later_games():
    windows=first_issuance_windows(schedule()['games'])
    assert [t.isoformat() for t in windows]==[
        '2026-10-17T16:55:00+00:00','2026-10-17T22:55:00+00:00']
    assert len(first_issuance_windows(schedule()['games'][:3]))==1


def test_later_bundle_accepts_evening_report_but_never_post_puck_early_report(tmp_path):
    con=open_db(str(tmp_path/'raw.sqlite'))
    day='2026-10-17'
    try:
        for eid,gid,clock in [('late-evening','2','21:00:00'),
                              ('post-puck-afternoon','1','21:00:00'),
                              ('revised-after-first-window','3','12:00:00')]:
            payload={'team':'BOS','venueHome':'Fixture Arena'}
            if eid=='revised-after-first-window':
                payload.update(sourceArticlePublishedAt=day+'T12:00:00Z',
                    sourceArticleModifiedAt=day+'T20:00:00Z')
            record_evidence(con,{'evidence_id':eid,'slate_date':day,'stage':'OFFICIAL',
                'game_id':gid,'kind':'MATCH_CONTEXT','source_url':'https://www.nhl.com/fixture',
                'observed_at':day+'T'+clock+'Z','payload':payload})
        early=build_day(con,day,tmp_path/'out',schedule())
        later=build_day(con,day,tmp_path/'out',schedule(),
            replay_cutoff=first_issuance_windows(schedule()['games'])[-1])
        assert early['snapshot']!=later['snapshot']
        def ids(bundle):
            p=tmp_path/'read.sqlite';p.write_bytes(gzip.decompress(
                (tmp_path/'out'/bundle['evidenceDb']).read_bytes()))
            db=sqlite3.connect(p)
            try:return {r[0] for r in db.execute('SELECT evidence_id FROM evidence')}
            finally:db.close()
        assert ids(early)==set()
        assert ids(later)=={'late-evening','revised-after-first-window'}
        snap=json.loads((tmp_path/'out'/later['snapshot']).read_text())
        assert len(snap['games'])==4  # preserve official calendar; engine excludes started game
    finally:con.close()


def test_replay_tries_later_window_only_until_first_card(monkeypatch,tmp_path):
    calls=[]
    bundles=[{'cutoff':'2026-10-17T16:55:00Z'},
             {'cutoff':'2026-10-17T22:55:00Z'},
             {'cutoff':'2026-10-17T23:55:00Z'}]
    def attempt(root,day,stage,bundle):
        calls.append(bundle['cutoff'])
        return {'engineResult':{'card':{'fingerprint':'FIRST'} if len(calls)==2 else None},
            'gateCertification':{'selectedCoreOnlyFullyCertified':len(calls)==2}}
    monkeypatch.setattr(replay,'_replay_attempt',attempt)
    result=replay.replay_day(tmp_path,'2026-10-17','PROJECTED',
        {**bundles[0],'laterPregameAttempts':bundles[1:]})
    assert calls==[b['cutoff'] for b in bundles[:2]]
    assert result['engineResult']['card']['fingerprint']=='FIRST'
    assert len(result['pregameLifecycleAttempts'])==2
