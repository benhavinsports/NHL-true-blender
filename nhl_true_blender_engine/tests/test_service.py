import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
from nhl_true_blender_engine.storage import open_db, save_card, get_card, fingerprint
from nhl_true_blender_engine.sources import NHLClient, official_slate, official_final_grade, SourceUnavailable
from nhl_true_blender_engine.server import app
from nhl_true_blender_engine.enrichment import ingest, attach
from nhl_true_blender_engine.tests.test_engine import DATE, FUTURE, evidence, snapshot, SRC
from nhl_true_blender_engine.engine import execute


@pytest.mark.asyncio
async def test_official_collector_two_teams_and_403_propagates(tmp_path):
    def handler(req):
        if req.url.path.endswith('/score/2026-11-26'):
            return httpx.Response(200,json={'games':[
                {'id':2026020311,'awayTeam':{'abbrev':'AAA'},'homeTeam':{'abbrev':'BBB'},
                 'startTimeUTC':'2026-11-26T23:00:00Z','gameState':'FUT'}]})
        if '/roster/AAA/' in req.url.path or '/roster/BBB/' in req.url.path:
            return httpx.Response(200,json={'forwards':[{'id':1001,'firstName':{'default':'A'},
               'lastName':{'default':'Skater'},'positionCode':'C'}],
               'defensemen':[{'id':1002,'firstName':{'default':'B'},
               'lastName':{'default':'Skater'},'positionCode':'D'}],
               'goalies':[{'id':2001,'positionCode':'G'}]})
        return httpx.Response(403, json={'error':'blocked'})
    transport=httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as hc:
        nhl=NHLClient(hc)
        db=open_db(str(tmp_path/'db.sqlite'))
        slate=await official_slate(nhl,'2026-11-26',db)
        assert len(slate['games'])==1
        assert len(slate['games'][0]['rosters']['AAA']['data']['players'])==2
        assert len(slate['games'][0]['rosters']['BBB']['data']['players'])==2
        assert db.execute('SELECT COUNT(*) FROM evidence').fetchone()[0]==3
        with pytest.raises(SourceUnavailable,match='403'):
            await nhl.boxscore(2026020311)
        db.close()


def test_different_first_writers_are_serialized(tmp_path):
    path=str(tmp_path/'race.sqlite')
    con=open_db(path)
    con.close()
    legs=[]
    for i in range(3):
        legs.append({'gameId':str(i+100),'playerId':str(i+10),'player':'P'+str(i),
                     'path':'PRIMARY','startUTC':FUTURE,'sourceIds':[SRC],
                     'gameState':'FUT'})
    def write(i):
        c=open_db(path)
        try:
            v=[dict(x) for x in legs]
            if i%2:v[0]['playerId']='different'
            try:return save_card(c,DATE,'PROJECTED',v,3)['fingerprint']
            except ValueError:return 'REJECTED'
        finally:c.close()
    with ThreadPoolExecutor(max_workers=8) as tp:
        results=list(tp.map(write,range(18)))
    c=open_db(path)
    assert c.execute('SELECT COUNT(*) FROM cards').fetchone()[0]==1
    assert c.execute('SELECT COUNT(*) FROM card_versions').fetchone()[0]==1
    assert all(x in ('REJECTED',fingerprint(legs),fingerprint([{**legs[0],'playerId':'different'},*legs[1:]])) for x in results)
    assert any(x=='REJECTED' for x in results)
    c.close()


def test_backend_health_and_write_auth(tmp_path,monkeypatch):
    import nhl_true_blender_engine.server as s
    monkeypatch.setattr(s,'DB_PATH',str(tmp_path/'service.sqlite'))
    monkeypatch.setattr(s,'ENABLE_SCHEDULER',False)
    monkeypatch.setattr(s,'RUNNER_KEY','private-fixture-secret')
    with TestClient(s.app) as client:
        h=client.get('/api/health')
        assert h.status_code==200 and h.json()['backendProcess']=='RUNNING'
        assert h.json()['patchRegistryCount']==13
        assert client.get('/api/state?date='+DATE).json()['fullLiveG18Confirmed'] is False
        assert client.post('/api/jobs/projected?date='+DATE).status_code==403
        assert client.post('/api/evidence',json={}).status_code==403
        item={'evidence_id':'line-1','slate_date':DATE,'stage':'PROJECTED',
              'kind':'PLAYER_STATUS','game_id':'5001','player_id':'1010',
              'source_url':SRC,'observed_at':'2026-11-14T08:15:00-05:00',
              'payload':{'status':'PROJECTED_ACTIVE'}}
        r=client.post('/api/evidence',json=item,headers={'x-runner-key':'private-fixture-secret'})
        assert r.status_code==200 and r.json()['inserted']
        assert client.post('/api/evidence',json=item,headers={'x-runner-key':'private-fixture-secret'}).json()['inserted'] is False
        assert client.get('/api/state?date='+DATE).json()['evidenceRows']==1


def test_grade_final_frozen_replacement_identity(tmp_path):
    con=open_db(str(tmp_path/'db.sqlite'))
    initial=execute(con,snapshot(),DATE,'PROJECTED')['card']
    assert initial
    altered=[dict(x) for x in initial['current_legs']]
    altered[0]['playerId']='new-recipient'
    from nhl_true_blender_engine.storage import record_evidence
    record_evidence(con,{'evidence_id':'source-1','slate_date':DATE,'stage':'CONFIRMED',
            'game_id':altered[0]['gameId'],'player_id':altered[0]['playerId'],
            'kind':'GOALIE_PROFILE','source_url':SRC,'observed_at':'2026-11-15T09:00:00Z',
            'payload':{'goalie':'new'}})
    audit={'baselineFingerprint':initial['fingerprint'],'triggerEvidenceId':'source-1',
            'oldValue':'old goalie','newValue':'new goalie',
            'affectedGates':['G0','G3','G5'],'dependentGates':['G10.5','G17'],
            'priorSurvivorFailure':{'failedGate':'G5','sourceIds':['source-1']},
            'g105EveryChallenger':{'comparisonRows':[{'challengerId':'1010','status':'DEFEATED'}]},
            'g17Contradictions':{'sourceIds':['source-1'],'review':'new goalie branch'},
            'newFingerprint':fingerprint(altered)}
    updated=save_card(con,DATE,'MIXED',altered,3,audit=audit)
    goal_counts={(leg['gameId'],leg['playerId']):1 for leg in updated['current_legs']}
    from nhl_true_blender_engine.storage import grade_frozen_card
    graded=grade_frozen_card(con,DATE,goal_counts,[SRC],True)
    assert graded['result']=='WIN'
    assert graded['legs'][0]['playerId']=='new-recipient'
    assert get_card(con,DATE)['initial_legs'][0]['playerId']!='new-recipient'
    con.close()


@pytest.mark.asyncio
async def test_watch_baseline_silent_then_material_change(tmp_path):
    from nhl_true_blender_engine.sources import collect_watch
    con=open_db(str(tmp_path/'watch.sqlite'))
    snap=snapshot(2)
    before=await collect_watch(None,con,DATE,snap)
    # Both independently measured goalie starter reports per matchup are
    # now real source-backed G0 evidence; baseline records include each one,
    # plus the eligible skater role category where available.
    assert before['initialBaselinesSavedWithoutAlert']==6
    assert before['verifiedMaterialChanges']==0
    assert con.execute('SELECT COUNT(*) FROM watch_events').fetchone()[0]==0
    repeat=await collect_watch(None,con,DATE,snap)
    assert repeat['verifiedMaterialChanges']==0
    snap['games'][0]['goalies']['T1B'][0]['data']['status']='EXPECTED'
    changed=await collect_watch(None,con,DATE,snap)
    assert changed['verifiedMaterialChanges']==1
    assert con.execute('SELECT COUNT(*) FROM watch_events').fetchone()[0]==1
    con.close()


@pytest.mark.asyncio
async def test_official_end_to_end_grade_uses_pbp_and_boxscore(tmp_path):
    con=open_db(str(tmp_path/'official_grade.sqlite'))
    c=execute(con,snapshot(),DATE,'PROJECTED')['card']
    assert c
    by_id={int(leg['gameId']):leg['playerId'] for leg in c['current_legs']}
    def handler(req):
        path=req.url.path
        if path.endswith('/score/'+DATE):
            return httpx.Response(200,json={'games':[
               {'id':int(l['gameId']),'awayTeam':{'abbrev':'AAA'},
                'homeTeam':{'abbrev':'BBB'},'startTimeUTC':l['startUTC'],
                'gameState':'OFF'} for l in c['current_legs']]})
        if '/gamecenter/' in path:
            gid=int(path.split('/gamecenter/')[1].split('/')[0]);pid=int(by_id[gid]);
            goals=0 if gid==5002 else 1
            if path.endswith('/play-by-play'):
                return httpx.Response(200,json={'plays':[
                 {'typeDescKey':'goal','periodDescriptor':{'periodType':'REG'},
                  'eventId':gid*10,'details':{'scoringPlayerId':pid}}] if goals else []})
            if path.endswith('/boxscore'):
                return httpx.Response(200,json={'playerByGameStats':{
                  'homeTeam':{'forwards':[{'playerId':pid,'goals':goals}],'defense':[]},
                  'awayTeam':{'forwards':[],'defense':[]}}})
        return httpx.Response(404)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as hc:
        result=await official_final_grade(NHLClient(hc),con,DATE)
    assert result['status']=='GRADED_OFFICIAL_GOAL_EVENTS'
    assert result['grade']['result']=='LOSS'
    assert [x['result'] for x in result['grade']['legs']].count('HIT')==2
    assert len(result['grade']['official_sources'])==7
    con.close()


def test_engine_auto_replaces_only_after_verified_confirmed_new_goalie(tmp_path):
    from nhl_true_blender_engine.storage import record_evidence
    con=open_db(str(tmp_path/'replace.sqlite'))
    first=execute(con,snapshot(),DATE,'PROJECTED')['card']
    assert first is not None
    s=snapshot()
    selected_game=s['games'][0]
    goalie=selected_game['goalies']['T1B'][0]
    goalie['data']['goalieId']='brand-new-confirmed-goalie'
    goalie['evidenceId']='goalie-confirmed-id'
    main=selected_game['rosters']['T1A']['data']['players'][0]
    main['release']['data']['zone']='point'  # source-based change makes old route miss target goalie
    challenger=selected_game['rosters']['T1A']['data']['players'][1]
    challenger['contradictions']['evidenceId']='fresh-contradiction-review'
    for rid,kind in [('goalie-confirmed-id','GOALIE_PROFILE'),
                     ('fresh-contradiction-review','PLAYER_CONTRADICTIONS')]:
        record_evidence(con,{'evidence_id':rid,'slate_date':DATE,'stage':'CONFIRMED',
           'game_id':selected_game['id'],'player_id':challenger['id'],
           'kind':kind,'source_url':SRC,'observed_at':'2026-11-14T12:00:00-05:00',
           'payload':{'documented':'yes','review':'direct release vs goalie location'}})
    result=execute(con,s,DATE,'CONFIRMED')
    assert result['card'],result['errors']
    card=result['card']
    assert card['revision']==2
    assert card['card_id']==first['card_id']
    assert card['initial_legs'][0]['playerId']=='1010'
    assert card['current_legs'][0]['playerId']=='1011'
    version=con.execute('SELECT rationale FROM card_versions WHERE revision=2').fetchone()[0]
    assert 'GATE_VALIDATED_REPLACEMENT' in version
    con.close()