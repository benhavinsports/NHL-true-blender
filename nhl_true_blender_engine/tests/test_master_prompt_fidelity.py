"""Behavioral regressions for the supplied complete master execution prompt."""
import copy
import json
import asyncio
import pytest
from nhl_true_blender_engine.shooter_mechanism import (
    mechanism_events, shooter_mechanism, SOURCE_TYPE)
from nhl_true_blender_engine.engine import execute, MASTER
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import ingest, attach
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.dashboard_export import export_dashboard
from nhl_true_blender_engine.semantic_certification import nonblocking_overlay_review
from nhl_true_blender_engine.source_recovery import recovery_snapshot
from nhl_true_blender_engine.official_context import collect_context
from nhl_true_blender_engine.tests.test_engine import snapshot, snapshot_without_shifts, DATE, evidence
from scripts.publish_site_state import export_run
from scripts.verify_published_core import verify_published_core

def shot(player='1010', **changed):
    return {**{'gameId':'2026020001','eventId':'23','date':'2026-11-01',
        'shooterId':player,'type':'shot-on-goal','shotType':'wrist',
        'x':80,'y':3,'period':1,'timeInPeriod':'04:12',
        'situationCode':'1551','goalieId':'2000',
        'sourceUrl':'https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play'},
        **changed}

def mechanism(player, events):
    rows=mechanism_events(events,player,DATE)
    return evidence({'sourceType':SOURCE_TYPE,'playerId':player,
                     'slateDate':DATE,'events':rows},
                    'https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play')

def own_scene():
    # Translate the synthetic generic slot to a supported coordinate bin.
    s=json.loads(json.dumps(snapshot()).replace('"slot"','"Low Slot"'))
    p=s['games'][0]['rosters']['T1A']['data']['players'][0]
    p['release']['data']['archetype']='OBSERVED_OWN_SHOT_ORIGIN'
    return s,p

def test_origin_counts_cannot_pass_g4_or_archetype_step7(tmp_path):
    s,p=own_scene()
    con=open_db(str(tmp_path/'origin.sqlite'))
    try:
        result=execute(con,s,DATE,'CONFIRMED')
        row=con.execute("SELECT disposition,details FROM gates WHERE player_id=? AND gate='G4'",
                        (p['id'],)).fetchone()
        assert row['disposition']=='NOT_EXECUTED'
        ev=json.loads(row['details'])['evidence']
        tag=next(x for x in ev['originalFunctionEvidence'] if x['step']=='Step7')
        assert tag['disposition']=='NOT_EXECUTED'
        assert tag['evidence']['archetype'] is None
        assert result['card'] is None
    finally:
        con.close()

def test_own_dated_pbp_action_flows_through_ingestion_g4_and_step7(tmp_path):
    s,p=own_scene()
    con=open_db(str(tmp_path/'action.sqlite'))
    try:
        obs=mechanism(p['id'],[shot()])
        ingest(con,{'evidence_id':'own-action','slate_date':DATE,'stage':'CONFIRMED',
            'game_id':s['games'][0]['id'],'player_id':p['id'],
            'kind':'PLAYER_SHOT_MECHANISM','source_url':obs['sourceUrl'],
            'observed_at':obs['observedAt'],'payload':obs['data']})
        attach(con,s,DATE,'CONFIRMED')
        result=execute(con,s,DATE,'CONFIRMED')
        row=con.execute("SELECT disposition,details FROM gates WHERE player_id=? AND gate='G4'",
                        (p['id'],)).fetchone()
        assert row['disposition']=='PASS'
        ev=json.loads(row['details'])['evidence']
        assert ev['archetype']=='observed wrist release'
        assert ev['individualMechanismReview']['ownMechanismEvents'][0]['eventId']=='23'
        tag=next(x for x in ev['originalFunctionEvidence'] if x['step']=='Step7')
        assert tag['disposition']=='PASS'
        assert tag['evidence']['sourceTaggedBeforeFinalPick'] is True
        assert result['card'] is not None, result['errors']
    finally:
        con.close()

@pytest.mark.parametrize('change',[
    {'shooterId':'another-player'}, {'date':DATE}, {'shotType':None},
    {'sourceUrl':'https://unrelated.example/pbp'}, {'x':40,'y':3},
    {'eventId':None},
])
def test_wrong_actor_date_source_or_area_cannot_invent_archetype(change):
    _,p=own_scene()
    p['shotMechanism']=mechanism(p['id'],[shot(**change)])
    proof=shooter_mechanism(p,p['release']['data'],DATE)
    assert proof['supported'] is False
    assert proof['archetype'] is None

def test_duplicate_pbp_events_and_other_players_are_not_new_evidence():
    rows=mechanism_events([shot(),shot(),shot('not-owner')],'1010',DATE)
    assert len(rows)==1
    assert rows[0]['shotType']=='wrist'
    assert rows[0]['situationCode']=='1551'

def test_optional_shift_uncertainty_survives_save_export_and_publication(tmp_path):
    con=open_db(str(tmp_path/'optional.sqlite'))
    root=tmp_path/'state'
    try:
        s=snapshot_without_shifts()
        result=execute(con,s,DATE,'CONFIRMED')
        result['gateCertification']=certify_gates(con,DATE,'CONFIRMED',3)
        status=export_run(con,DATE,'CONFIRMED',result,root)
        assert status['publishedToSite'] is True
        export_dashboard(con,DATE,'CONFIRMED',s,root)
        proof=verify_published_core(root,DATE)
        assert proof['status']=='ORIGINAL_G0_G18_CORE_VERIFIED'
        gates=json.loads((root/'site_gates'/f'{DATE}.json').read_text())
        for leg in gates['legs']:
            g9=next(g for g in leg['gateDetails'] if g['gate']=='G9')
            shift=next(x for x in g9['evidence']['originalFunctionEvidence'] if x['step']=='Step8')
            assert shift['disposition']=='NOT_EXECUTED'
            assert shift['evidence']['actualShiftByShiftObserved'] is False
    finally:
        con.close()

def test_nonblocking_flag_cannot_excuse_contradiction_or_required_step():
    ev={'independentOverlayEvaluation':True,'checkedBeforeG18':True,
        'masterGateVerdictCopied':False,'nonblocking':True,
        'actualShiftByShiftObserved':False}
    assert nonblocking_overlay_review('Step8',ev,'NOT_EXECUTED')
    assert not nonblocking_overlay_review('Step8',ev,'ELIMINATED')
    assert not nonblocking_overlay_review('Step7',ev,'NOT_EXECUTED')
    assert not nonblocking_overlay_review('Step8',{**ev,'actualShiftByShiftObserved':True},'NOT_EXECUTED')

def test_source_retry_does_not_refetch_qualified_or_started_matchups(tmp_path):
    con=open_db(str(tmp_path/'retry.sqlite'))
    try:
        s=snapshot()
        # Only the middle game's opposing goalie evidence is unavailable.
        s['games'][1]['goalies']={}
        result=execute(con,s,DATE,'CONFIRMED')
        scoped=recovery_snapshot(con,s,DATE,'CONFIRMED',result)
        assert [g['id'] for g in scoped['games']]==[s['games'][1]['id']]
        assert len(s['games'])==3
        assert scoped['games'][0] is s['games'][1]
        s['games'][1]['gameState']='LIVE'
        assert recovery_snapshot(con,s,DATE,'CONFIRMED',result)['games']==[]
    finally:
        con.close()

def test_context_retains_real_schedule_sequence_without_inventing_travel(tmp_path):
    class Client:
        async def get(self,route):
            return {'url':'https://api-web.nhle.com/v1/'+route,
                'observedAt':'2026-11-21T12:00:00Z','data':{'games':[
                    {'id':1,'gameDate':'2026-11-20','gameState':'FINAL',
                     'startTimeUTC':'2026-11-21T00:00:00Z',
                     'homeTeam':{'abbrev':'NYI'},'awayTeam':{'abbrev':'NYR'},
                     'venue':{'default':'Previous Arena'}},
                    {'id':2,'gameDate':'2026-11-22','gameState':'FUT',
                     'homeTeam':{'abbrev':'BOS'},'awayTeam':{'abbrev':'NYR'}}]}}
    con=open_db(str(tmp_path/'context.sqlite'))
    try:
        s={'games':[{'id':'3','away':'NYR','home':'NJD',
            'venue':{'default':'Current Arena'},'startUTC':'2026-11-22T00:00:00Z',
            'officialSourceUrl':'https://api-web.nhle.com/v1/score/2026-11-21'}]}
        result=asyncio.run(collect_context(Client(),con,s,'2026-11-21','PROJECTED'))
        assert result['contextGames']==1
        row=con.execute("SELECT payload FROM evidence WHERE kind='MATCH_CONTEXT'").fetchone()
        data=json.loads(row['payload'])
        assert data['awayBackToBack'] is True
        sequence=data['teamScheduleSequences']['NYR']
        assert [r['gameId'] for r in sequence]==['1']
        assert sequence[0]['venue']['default']=='Previous Arena'
        transition=data['scheduledVenueTransitions']['NYR']
        assert transition['currentVenue']['default']=='Current Arena'
        assert transition['previousStartUTC']=='2026-11-21T00:00:00Z'
        assert data['scheduleSequenceIsNotObservedFlightOrFatigue'] is True
        assert data['travelMiles'] is None
    finally:
        con.close()

def test_pressure_from_other_areas_does_not_pass_selected_route_continuation(tmp_path):
    s=snapshot()
    p=s['games'][0]['rosters']['T1A']['data']['players'][0]
    # Complete reconciled PBP sample, but no own on-net shot in the selected
    # slot. General individual shots elsewhere are not this route's pressure.
    p['recentOrigin']['data']['zoneCounts']={}
    con=open_db(str(tmp_path/'pressure.sqlite'))
    try:
        execute(con,s,DATE,'CONFIRMED')
        row=con.execute("SELECT disposition,details FROM gates WHERE player_id=? AND gate='G11'",
                        (p['id'],)).fetchone()
        assert row['disposition']=='ELIMINATED'
        ev=json.loads(row['details'])['evidence']
        assert ev['shotContinuation']['repeatedOwnShotPressure'] is True
        assert ev['currentShotPressureInSelectedRoute'] is False
        assert ev['selectedRouteRecentOrigin']['shotsOnGoal']==0
        sub=ev['originalFunctionEvidence'][0]
        assert sub['step']=='Step9' and sub['disposition']=='ELIMINATED'
    finally:
        con.close()

def test_explicit_live_request_uses_existing_date_phase_authority(monkeypatch,tmp_path):
    from scripts import automatic_blender_cycle as cycle
    monkeypatch.chdir(tmp_path)
    folder=tmp_path/'.github'
    folder.mkdir()
    request=folder/'nhl-live-validation.json'
    request.write_text(json.dumps({'date':'2026-11-21','mode':'projected'}))
    for key in ('REQUESTED_DATE','REQUESTED_MODE','GITHUB_ENV'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('TRIGGER_EVENT','push')
    calls=[]
    monkeypatch.setattr(cycle,'execute_commands',lambda day,mode:calls.append((day,mode)))
    cycle.main()
    assert calls==[('2026-11-21','projected')]
    request.write_text(json.dumps({'date':'2026-11-21','mode':'projected','players':['injected']}))
    with pytest.raises(SystemExit):
        cycle.main()
    assert len(calls)==1
