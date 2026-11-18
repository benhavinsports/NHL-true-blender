import json
import sqlite3
from datetime import datetime,timedelta,timezone
from tempfile import NamedTemporaryFile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from nhl_true_blender_engine.storage import open_db, save_card, get_card, grade_frozen_card, record_evidence, record_watch
from nhl_true_blender_engine.engine import execute, MASTER, OVERLAY, SCORER_GATE_ORDER, EXECUTION_ORDER, STEPS_BY_GATE, PATCH_IDS
from nhl_true_blender_engine.sources import credited_goals_from_pbp, normalize_games, SourceUnavailable

SRC='https://example.org/official-verifiable-fixture-not-live'
FUTURE=(datetime.now(timezone.utc)+timedelta(days=12)).isoformat().replace('+00:00','Z')
DATE=(datetime.now(timezone.utc)+timedelta(days=12)).date().isoformat()


def evidence(data,source=SRC):
    return {'sourceUrl':source,'observedAt':'2026-01-01T05:00:00Z','data':data}


def skater(pid,zone,attempts,goals,avail='CONFIRMED',who=False):
    entries=[{'date':'2026-11-01','goalId':f'goal-{pid}-{k}','sourceUrl':SRC}
             for k in range(goals)]
    return {'id':str(pid),'name':'Skater '+str(pid),'position':'D' if who else 'C',
            'jersey':pid%90+1,'availability':avail,
            'release':evidence({'archetype':'own wrist/snap release','zone':zone,'attempts':attempts,'ownedGoals':goals}, source=SRC+'/shot-origin/'+str(pid)),
            'deployment':evidence({'EV':'EV2','PP':'PP2','PK':'optional','status':'CONFIRMED'}),
            'gameLog':evidence({'appearances':[{'date':'2026-11-01','shots':attempts},{'date':'2026-11-02','shots':1}]}),
            'mappedGoals':evidence({'goals':entries}),
            'officialGoalTotal':evidence({'goals':goals}),
            'finishOwnership':evidence({'recipient':True,'creditedGoalsVerified':True}),
            'recentOrigin':evidence({
                'sourceType':'OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN',
                'scope':'RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY',
                'rinkBinsApproximateNotNhlEdgePolygons':True,
                'historicalOwnGoalCreditOnly':True,
                'zoneCounts':{zone:{'shotsOnGoal':attempts,'ownedGoals':goals,
                    'sourceUrls':[SRC+'/recent-origin/'+str(pid)]}}}),
            'pressure':evidence({'recentAppearanceShots':[3,4],
                'appearances':[{'date':'2026-11-01'},{'date':'2026-11-02'}],
                'evidenceType':'OFFICIAL_HISTORICAL_SHOT_EVENTS'}),
            'contradictions':evidence({
                'sourceType':'FIXTURE_STRUCTURED_G17','unresolved':False,
                'anatomicalWeaknessCertified':True,
                'goalieStrengthReview':{'matchedWeakAreas':1,'strongerAreaContradiction':False},
                'lineupDisagreementReview':{'isTrulyConfirmed':True,
                                           'hasProjectedOrConfirmedRole':True},
                'strongestRivalReview':{'everyRivalReviewed':True,
                                        'eachSameLaneDefeated':True}}),
            **({'whoAnomaly':evidence({'directIndependentRoute':True,'mechanism':'blue line chaos goal'})} if who else {})}


def game(idx,win=True):
    away=f'T{idx}A';home=f'T{idx}B'
    main=skater(1000+idx*10, 'slot',28,3,who=(idx==3))
    rival=skater(1000+idx*10+1,'slot',11,1)
    d=skater(1000+idx*10+2,'point',1,0,'OUT')
    def goalie(gid,team):
        return evidence({'goalieId':gid,'team':team,'status':'CONFIRMED','weakZones':{'slot':{'savePct':.8}},
            'strengthZones':{'point':{'savePct':.93}},'counterevidence':'strong at distance',
            'sample':'dated 200 shot profile'})
    # A complete synthetic baseline has independently attributed team shifts.
    # Negative tests remove these receipts to verify that no Core is locked.
    shift_url='https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId%3D2026020300'
    shift_data={'shiftByShift':[{
        'zone':'slot','gameId':'2026020300','eventId':'11',
        'period':1,'eventClock':'04:12',
        'defendingOnIcePlayerIds':['11','22','33'],
        'officialShiftChartUrl':shift_url,
        'officialPlayByPlayUrl':'https://api-web.nhle.com/v1/gamecenter/2026020300/play-by-play'}],
        'shiftSourceUrls':[shift_url],'actualDefensiveShiftMatches':1}
    return {'id':str(5000+idx),'date':DATE,'away':away,'home':home,'startUTC':FUTURE,'gameState':'FUT',
        'goalies':{
            away:[evidence({'goalieId':'g'+away,'team':away,
                'status':'CONFIRMED','weakZones':{},
                'strengthZones':{'slot':{'savePct':.97}},
                'sample':{'allZoneObservations':80,'source':'independent synthetic goalie report'},
                'observedAreas':{'slot':{'shotsAgainst':80,'goalsAgainst':2,'saves':78}},
                'sourceReviewed':True,
                'counterevidence':{'reviewedIndependentOrigins':['slot']},
                'sourceClass':'DERIVED_RINK_ORIGIN_NOT_ANATOMICAL'})],
            home:[goalie('g'+home,home)]},
        'rosters':{away:evidence({'players':[main,rival,d]}),home:evidence({'players':[]})},
        'context':evidence({'venue':home,'rest':'one day both teams','travel':'neutral'}),
        'coverage':{away:evidence({
                        'greenWeakZones':['slot'],'redStrongZones':['point'],
                        'sourceType':'OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY',
                        'comparison':'RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN',
                        'lowShotVolumeIsNotEvidenceOfDefensiveStrength':True,
                        'zoneConcessions':{'slot':{
                            'attemptsAgainst':24,'gameCount':8,'peerTeamsCompared':8,
                            'attemptsPerGame':3.0,'peerMedianAttemptsPerGame':1.5}},
                        **shift_data}),
                    home:evidence({
                        'greenWeakZones':['slot'],'redStrongZones':['point'],
                        'sourceType':'OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY',
                        'comparison':'RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN',
                        'lowShotVolumeIsNotEvidenceOfDefensiveStrength':True,
                        'zoneConcessions':{'slot':{
                            'attemptsAgainst':24,'gameCount':8,'peerTeamsCompared':8,
                            'attemptsPerGame':3.0,'peerMedianAttemptsPerGame':1.5}},
                        **shift_data})}}


def snapshot(n=3):return {'games':[game(i+1) for i in range(n)]}


@pytest.fixture
def con(tmp_path):
    c=open_db(str(tmp_path/'test.sqlite'))
    yield c
    c.close()


def test_full_structural_three_game_run(con):
    assert SCORER_GATE_ORDER == ([f'G{i}' for i in range(1,11)] +
                                 ['G10.5'] + [f'G{i}' for i in range(11,19)])
    assert MASTER == ['G0'] + SCORER_GATE_ORDER
    assert len(MASTER)==20 and MASTER[11]=='G10.5' and len(OVERLAY)==16
    assert EXECUTION_ORDER == MASTER
    assert EXECUTION_ORDER[-1]=='G18'
    assert EXECUTION_ORDER.index('G10.5') < EXECUTION_ORDER.index('G11')
    assert len(PATCH_IDS)==13
    res=execute(con,snapshot(),DATE,'CONFIRMED')
    assert res['g0Directions']==6 and res['g0Complete']==6
    assert res['eligibleSkaterRows']==9
    assert res['gateRows']==9*len(MASTER)+6
    assert res['uniqueGameSurvivors']==3
    assert res['card'] is not None,res['errors']
    legs=res['card']['current_legs']
    assert {x['player'] for x in legs}=={'Skater 1010','Skater 1020','Skater 1030'}
    assert {x['path'] for x in legs}=={'PRIMARY','WHO'}
    assert len({x['gameId'] for x in legs})==3
    assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0]==1
    assert con.execute('SELECT COUNT(*) FROM gates').fetchone()[0]==9*len(MASTER)+6
    stored=con.execute("SELECT gate,details FROM gates WHERE slate_date=? AND stage='CONFIRMED' AND game_id='5001' AND player_id='1010'",(DATE,)).fetchall()
    stored.sort(key=lambda row:json.loads(row['details']).get('executionIndex',-1))
    assert [row['gate'] for row in stored]==EXECUTION_ORDER
    assert [json.loads(row['details'])['executionIndex'] for row in stored]==list(range(len(EXECUTION_ORDER)))
    assert 'PATCH-NOV12-G10.5-EXPLICIT-SEPARATION' in con.execute("SELECT details FROM gates WHERE gate='G10.5' AND player_id='1010'").fetchone()[0]


def test_missing_opposing_goalie_profile_blocks_entire_g18(con):
    s=snapshot()
    s['games'][2]['goalies'][s['games'][2]['home']]=[]
    result=execute(con,s,DATE,'CONFIRMED')
    assert result['g0Complete']==5
    assert result['card'] is None
    assert any('G0' in e for e in result['errors'])


def test_missing_g10_5_challenger_release_blocks_core(con):
    s=snapshot()
    del s['games'][0]['rosters']['T1A']['data']['players'][1]['release']
    result=execute(con,s,DATE,'CONFIRMED')
    assert result['card'] is None
    assert result['uniqueGameSurvivors']==2


def test_missing_goal_map_does_not_pass_g7(con):
    s=snapshot()
    s['games'][0]['rosters']['T1A']['data']['players'][0]['officialGoalTotal']['data']['goals']=4
    result=execute(con,s,DATE,'CONFIRMED')
    assert not result['card']
    rows=con.execute("SELECT * FROM gates WHERE player_id='1010' AND gate='G7'").fetchall()
    assert rows and rows[0]['disposition']=='NOT_EXECUTED'


def test_roster_scratches_still_have_g2_rows(con):
    result=execute(con,snapshot(),DATE,'CONFIRMED')
    row=con.execute("SELECT disposition FROM gates WHERE player_id='1012' AND gate='G2'").fetchone()
    assert row['disposition']=='ELIMINATED'


def test_card_idempotent_stage_progression_and_locked_identity(con):
    res=execute(con,snapshot(),DATE,'PROJECTED')
    first=res['card']
    assert first
    again=save_card(con,DATE,'PROJECTED',first['current_legs'],3)
    assert again['revision']==1
    advanced=save_card(con,DATE,'MIXED',first['current_legs'],3)
    assert advanced['revision']==2 and advanced['card_id']==first['card_id']
    assert con.execute('SELECT COUNT(*) FROM cards').fetchone()[0]==1
    with pytest.raises(ValueError,match='demote'):
        save_card(con,DATE,'PROJECTED',first['current_legs'],3)


def test_changed_recipient_rejected_without_sourced_audit(con):
    legs=execute(con,snapshot(),DATE,'PROJECTED')['card']['current_legs']
    changed=[dict(x) for x in legs]
    changed[0]['playerId']='something-else'
    with pytest.raises(ValueError,match='replacement lacks'):
        save_card(con,DATE,'MIXED',changed,3)
    assert get_card(con,DATE)['revision']==1


def test_sourced_pre_puck_replacement_and_late_rejection(con):
    c=execute(con,snapshot(),DATE,'PROJECTED')['card']
    modified=[dict(x) for x in c['current_legs']]
    modified[0]['playerId']='new-recipient'
    from nhl_true_blender_engine.storage import fingerprint
    record_evidence(con,{'evidence_id':'trigger-1','slate_date':DATE,'stage':'CONFIRMED',
            'game_id':modified[0]['gameId'],'player_id':modified[0]['playerId'],'kind':'GOALIE_PROFILE',
            'source_url':SRC,'observed_at':datetime.now(timezone.utc).isoformat(),
            'payload':{'new':'starter'}})
    audit={'baselineFingerprint':c['fingerprint'],'triggerEvidenceId':'trigger-1',
           'oldValue':'old projected starter','newValue':'new confirmed starter',
           'affectedGates':['G0','G3'],'dependentGates':['G5','G10.5','G17'],
           'priorSurvivorFailure':{'failedGate':'G5','sourceIds':['trigger-1']},
           'g105EveryChallenger':{'comparisonRows':[{'old':'lost on independent direct route','sourceIds':['trigger-1']}]},
           'g17Contradictions':{'sourceIds':['trigger-1'],'result':'confirmed different goalie'},
           'newFingerprint':fingerprint(modified)}
    save=save_card(con,DATE,'MIXED',modified,3,audit=audit)
    assert audit['triggerNewerThanBaselineVersion'] is True
    assert audit['baselineVersionCreatedAt']
    assert audit['triggerObservedAt']
    assert save['revision']==2
    assert save['initial_legs'][0]['playerId']!=save['current_legs'][0]['playerId']
    more=[dict(x) for x in modified];more[0]['playerId']='newer'
    audit['baselineFingerprint']=save['fingerprint']
    audit['newFingerprint']=fingerprint(more)
    with pytest.raises(ValueError,match='Frozen'):
        save_card(con,DATE,'CONFIRMED',more,3,audit=audit,
                  now=datetime.fromisoformat(FUTURE.replace('Z','+00:00'))+timedelta(seconds=1))


def test_official_grade_original_not_replacement(con):
    c=execute(con,snapshot(),DATE,'PROJECTED')['card']
    with pytest.raises(ValueError,match='officially final'):
        grade_frozen_card(con,DATE,{},[SRC],False)
    legs=c['initial_legs']
    goals={(str(leg['gameId']),str(leg['playerId'])):(1 if i!=1 else 0)
           for i,leg in enumerate(legs)}
    grade=grade_frozen_card(con,DATE,goals,[SRC],True)
    assert grade['result']=='LOSS'
    assert [x['result'] for x in grade['legs']].count('MISS')==1
    assert grade_frozen_card(con,DATE,goals,[SRC],True)==grade
    assert get_card(con,DATE)['grade']['hits']==2


def test_watcher_stops_after_game_start(con):
    event={'event_id':'new-confirmation','slate_date':DATE,'game_id':'5001',
        'category':'goalie','old':'EXPECTED','new':'CONFIRMED',
        'source_url':SRC,'dependent_gates':['G0','G3']}
    assert record_watch(con,event,FUTURE) is True
    assert record_watch(con,event,FUTURE) is False
    with pytest.raises(ValueError,match='frozen'):
        record_watch(con,{**event,'event_id':'late'},FUTURE,
                     now=datetime.fromisoformat(FUTURE.replace('Z','+00:00'))+timedelta(seconds=1))


def test_official_pbp_credited_only_no_shootout_or_assist():
    payload={'data':{'plays':[
        {'typeDescKey':'goal','eventId':10,'periodDescriptor':{'periodType':'REG'},'details':{'scoringPlayerId':31,'assist1PlayerId':88}},
        {'typeDescKey':'goal','eventId':11,'periodDescriptor':{'periodType':'SO'},'details':{'scoringPlayerId':31}},
        {'typeDescKey':'shot-on-goal','eventId':12,'details':{'shootingPlayerId':42}},
        {'typeDescKey':'goal','eventId':13,'periodDescriptor':{'periodType':'OT'},'details':{'scoringPlayerId':31}}
    ]}}
    goals,event_ids=credited_goals_from_pbp(payload)
    assert goals=={'31':2} and event_ids==[10,13]


def test_no_fake_core_on_missing_live_feed(con):
    r=execute(con,{'games':[]},DATE,'PROJECTED')
    assert not r['card'] and r['errors']
    assert con.execute('SELECT status FROM jobs').fetchone()[0]=='SOURCE_ERROR'


def test_ambiguous_more_than_three_games_never_top3_by_name(con):
    result=execute(con,snapshot(4),DATE,'CONFIRMED')
    assert result['uniqueGameSurvivors']==4
    assert result['card'] is None


def test_exact_two_game_slate_uses_core2_no_forced_who(con):
    result=execute(con,snapshot(2),DATE,'CONFIRMED')
    assert result['card'] is not None
    assert len(result['card']['current_legs'])==2
    assert len({x['gameId'] for x in result['card']['current_legs']})==2


def test_all_thirteen_patch_ids_mapped_into_real_gates():
    from nhl_true_blender_engine.engine import GATE_PATCHES
    actual={patch for items in GATE_PATCHES.values() for patch in items}
    assert set(PATCH_IDS)==actual


def test_missing_game_one_skater_trace_cannot_issue_card(con):
    from nhl_true_blender_engine.engine import verify_complete_matrix, gate_record, MASTER, OVERLAY, EXECUTION_ORDER
    s=snapshot()
    rows=[]
    for game in s['games']:
        for attack in (game['away'],game['home']):
            rows.append(gate_record(game,'GOALIE_DIRECTION:'+attack,'G0','PASS',{}))
        for team in (game['away'],game['home']):
            for p in game['rosters'][team]['data']['players']:
                for gate in EXECUTION_ORDER:
                    functions=[{'step':step,'disposition':'PASS','sourceIds':['https://www.nhl.com/'],
                                'evidence':{'independentOverlayEvaluation':True,
                                            'checkedBeforeG18':True,
                                            'masterGateVerdictCopied':False}}
                               for step in STEPS_BY_GATE[gate]
                               if not (p['id']=='1011' and step=='Step7')]
                    rows.append(gate_record(game,p['id'],gate,'PASS',
                        {'originalFunctionEvidence':functions}))
    selected={str(g['id']):{'attacker':g['away']} for g in s['games']}
    errors=verify_complete_matrix(s['games'],rows,[],now=datetime.now(timezone.utc),selected_directions=selected)
    assert any('1011' in e and 'Step7' in e for e in errors)
def snapshot_without_shifts(n=3):
    slate=snapshot(n)
    for game in slate['games']:
        for team in (game['away'],game['home']):
            data=game['coverage'][team]['data']
            for key in ('shiftByShift','shiftSourceUrls','actualDefensiveShiftMatches'):
                data.pop(key,None)
    return slate

def test_matrix_verifier_rejects_reordered_gate_rows(con):
    from nhl_true_blender_engine.engine import verify_complete_matrix,gate_record,EXECUTION_ORDER
    s=snapshot()
    rows=[]
    for game in s['games']:
        for attack in (game['away'],game['home']):
            rows.append(gate_record(game,'GOALIE_DIRECTION:'+attack,'G0','PASS',{}))
        for team in (game['away'],game['home']):
            for person in game['rosters'][team]['data']['players']:
                for gate in EXECUTION_ORDER:
                    rows.append(gate_record(game,person['id'],gate,'PASS',{}))
    game_id=str(s['games'][0]['id'])
    chosen=[i for i,row in enumerate(rows)
            if row['gameId']==game_id and row['playerId']=='1010']
    a=next(i for i in chosen if rows[i]['gate']=='G10.5')
    b=next(i for i in chosen if rows[i]['gate']=='G11')
    rows[a],rows[b]=rows[b],rows[a]
    directions={str(g['id']):{'attacker':g['away']} for g in s['games']}
    errors=verify_complete_matrix(s['games'],rows,[],
        now=datetime.now(timezone.utc),selected_directions=directions)
    assert any('1010' in error and 'wrong gate execution order' in error
               for error in errors)


def test_integrated_gate_evidence_uses_semantic_owners(con):
    """Step observations must affect the gate that consumes their evidence."""
    result=execute(con,snapshot(),DATE,'CONFIRMED')
    assert result['card'] is not None,result['errors']
    rows=con.execute(
        "SELECT gate,details FROM gates WHERE slate_date=? AND stage='CONFIRMED' "
        "AND game_id='5001' AND player_id='1010'",(DATE,)).fetchall()
    details={gate:json.loads(raw) for gate,raw in rows}
    expected={'G0':{'Step0'},'G1':{'Step2'},'G2':{'Step1'},
              'G4':{'Step5','Step7'},'G5':{'Step3','Step10'},
              'G6':{'Step6'},'G7':{'Step4'},'G9':{'Step8'},
              'G10.5':{'Step10.5'},'G11':{'Step9'},
              'G13':{'Step13'},'G14':{'Step11'},'G16':{'Step12'},
              'G17':{'Step14'}}
    for gate,steps in expected.items():
        proof=details[gate]['evidence']
        observations=proof['independentOverlayEvidence']
        assert {item['step'] for item in observations}==steps
        # Each source function now belongs to this one canonical gate row.
        assert proof['originalFunctionEvidence']==observations
        assert all(item['disposition']=='PASS' for item in observations)
    assert set(details)==set(MASTER)


def test_gate_time_trace_matches_persisted_decisions(con):
    """Prove the saved chronology and gate verdicts, not merely row counts."""
    result=execute(con,snapshot(),DATE,'CONFIRMED')
    assert result['card'] is not None,result['errors']
    rows=con.execute(
        "SELECT gate,disposition,details FROM gates WHERE slate_date=? "
        "AND stage='CONFIRMED' AND game_id='5001' AND player_id='1010'",
        (DATE,)).fetchall()
    chronological=sorted(rows,key=lambda row:json.loads(row[2])['executionIndex'])
    assert [row[0] for row in chronological]==EXECUTION_ORDER
    assert len(chronological)==len(set(row[0] for row in chronological))
    for gate in MASTER[:-1]:
        gate_row=next(row for row in chronological if row[0]==gate)
        content=json.loads(gate_row[2])['evidence']
        steps=content.get('independentOverlayEvidence',[])
        assert [item['step'] for item in steps]==STEPS_BY_GATE[gate]
        assert steps==content.get('originalFunctionEvidence',[])
        for fn in steps:
            assert fn['disposition']=='PASS'
            assert fn['evidence']['checkedBeforeG18'] is True
            assert fn['evidence']['masterGateVerdictCopied'] is False


def test_projected_status_cannot_erase_official_dressed_status():
    """Confirmed roster identity remains authoritative across source refreshes."""
    from nhl_true_blender_engine.enrichment import attach
    con=open_db(':memory:')
    game={'id':'status-game','away':'NYR','home':'NYI',
          'rosters':{'NYR':{'data':{'players':[{'id':'100','name':'Test Skater','availability':'DRESSED'}]}},
                     'NYI':{'data':{'players':[]}}},
          'goalies':{'NYR':[],'NYI':[]},'coverage':{}}
    # A later projected update must not erase a source-backed DRESSED record.
    record_evidence(con,{'evidence_id':'official-dressed','slate_date':DATE,
        'stage':'OFFICIAL','game_id':'status-game','player_id':'100',
        'kind':'PLAYER_STATUS','source_url':SRC,'observed_at':'2026-01-01T00:00:00Z',
        'payload':{'status':'DRESSED'}})
    record_evidence(con,{'evidence_id':'projected-later','slate_date':DATE,
        'stage':'CONFIRMED','game_id':'status-game','player_id':'100',
        'kind':'PLAYER_STATUS','source_url':SRC,'observed_at':'2026-01-01T01:00:00Z',
        'payload':{'status':'PROJECTED_ACTIVE'}})
    snap={'games':[game]}
    attach(con,snap,DATE,'CONFIRMED')
    player=game['rosters']['NYR']['data']['players'][0]
    assert player['availability']=='DRESSED'
    assert player['availabilitySource']['evidenceId']=='official-dressed'
    assert len(player['availabilityAlternatives'])==1


def test_four_survivor_games_keep_all_original_gate_evidence_without_g18_rank(con):
    """All four complete original gate matrices stay intact; G18 is card only."""
    s=snapshot(4)
    for game in s["games"]:
        for team in (game["away"],game["home"]):
            assert game["coverage"][team]["data"]["comparison"]==(
                "RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN")
    result=execute(con,s,DATE,"CONFIRMED")
    assert result["uniqueGameSurvivors"]==4
    # Four legitimate winners require earlier original rule resolution;
    # G18 cannot arbitrarily take three, regardless of source richness.
    assert result["card"] is None
    assert "PRE_CORE_REVIEW" in str(result["errors"])
    assert result["gateRows"]==12*len(EXECUTION_ORDER)+8
    for gid,pid in ((str(5000+i),str(1000+i*10)) for i in range(1,5)):
        rows=con.execute("""SELECT gate,disposition,details FROM gates
            WHERE slate_date=? AND stage='CONFIRMED'
              AND game_id=? AND player_id=?""",
            (DATE,gid,pid)).fetchall()
        chronological=sorted(rows,key=lambda x:json.loads(x["details"])["executionIndex"])
        assert [row["gate"] for row in chronological]==EXECUTION_ORDER
        assert all(row["disposition"]=="PASS" for row in chronological[:-1])
        # Unseparated game finalists are not permitted a final Core G18 PASS.
        assert chronological[-1]["gate"]=="G18"
        assert chronological[-1]["disposition"]=="NOT_EXECUTED"


def test_g18_semantic_rejection_never_enters_final_pool(con,monkeypatch):
    """G18 must not silently promote a pre-audit True despite failed proof."""
    import nhl_true_blender_engine.engine as engine
    original_audit=engine.audit_gate
    def reject_final(gate,evidence,source_ids,stage):
        if gate=="G18":
            return ["SYNTHETIC_MISSING_G18_PROOF"]
        return original_audit(gate,evidence,source_ids,stage)
    monkeypatch.setattr(engine,"audit_gate",reject_final)
    result=execute(con,snapshot(3),DATE,"CONFIRMED")
    assert result["card"] is None
    # Game-level G0-G17 survivors are still observed; final G18 proof
    # rejection blocks their promotion into the Core, not their existence.
    assert result["uniqueGameSurvivors"]==3
    assert "G18" in str(result["errors"])
    rows=con.execute("SELECT disposition FROM gates WHERE gate='G18'").fetchall()
    assert rows and all(x["disposition"]=="NOT_EXECUTED" for x in rows)


def test_stale_trigger_cannot_replace_core_or_fake_retraction_exception(con):
    """Changing code or replaying old goalie receipts never authorizes a swap."""
    first=execute(con,snapshot(),DATE,'PROJECTED')['card']
    proposed=[dict(x) for x in first['current_legs']]
    proposed[0]['playerId']='unverified-new-player'
    record_evidence(con,{
        'evidence_id':'stale-goalie-trigger','slate_date':DATE,
        'stage':'CONFIRMED','game_id':proposed[0]['gameId'],
        'player_id':proposed[0]['playerId'],'kind':'GOALIE_PROFILE',
        'source_url':SRC,'observed_at':'2026-01-01T05:00:00Z',
        'payload':{'goalieId':'not-a-live-goalie'}})
    from nhl_true_blender_engine.storage import fingerprint
    audit={
        'baselineFingerprint':first['fingerprint'],
        'triggerEvidenceId':'stale-goalie-trigger',
        'oldValue':{'player':'original'},'newValue':{'player':'replacement'},
        'affectedGates':['G0'],'dependentGates':['G10.5','G17'],
        'priorSurvivorFailure':{'failedGate':'G0','sourceIds':['stale-goalie-trigger']},
        'g105EveryChallenger':{'comparisonRows':[{'status':'DEFEATED'}]},
        'g17Contradictions':{'sourceIds':['stale-goalie-trigger']},
        'newFingerprint':fingerprint(proposed),
    }
    with pytest.raises(ValueError,match='predates or matches'):
        save_card(con,DATE,'MIXED',proposed,3,audit=audit)
    # This exception is only allowed for the exact archived November 17
    # invalid-G18 fingerprint. Supplying the string alone grants no rights.
    audit['exceptionScope']='NOV17_PREVIOUSLY_RETRACTED_FINGERPRINT_ONLY'
    with pytest.raises(ValueError,match='retraction exception'):
        save_card(con,DATE,'MIXED',proposed,3,audit=audit)
    still=get_card(con,DATE)
    assert still['fingerprint']==first['fingerprint']
    assert still['revision']==first['revision']
