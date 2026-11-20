import json
from copy import deepcopy
from datetime import datetime,timedelta

import pytest
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.storage import open_db,get_card
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.dashboard_export import export_dashboard
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE
from scripts.publish_site_state import export_run
from scripts.verify_published_core import verify_published_core


def test_started_leg_is_never_reopened_and_unstarted_incumbents_require_fresh_gates(tmp_path):
    con=open_db(str(tmp_path/'ledger.sqlite'))
    slate=snapshot(3)
    start=datetime.fromisoformat(slate['games'][0]['startUTC'].replace('Z','+00:00'))
    slate['games'][1]['startUTC']=(start+timedelta(hours=2)).isoformat()
    slate['games'][2]['startUTC']=(start+timedelta(hours=3)).isoformat()
    first=execute(con,slate,DATE,'CONFIRMED',now=start-timedelta(minutes=10))
    first['gateCertification']=certify_gates(con,DATE,'CONFIRMED',first['games'])
    export_dashboard(con,DATE,'CONFIRMED',slate,tmp_path)
    status=export_run(con,DATE,'CONFIRMED',first,tmp_path)
    assert status['selectedCoreFullyCertified'] is True
    before=get_card(con,DATE)
    saved=(tmp_path/'site_cards'/f'{DATE}.json').read_bytes()
    now=start+timedelta(minutes=5)
    result=execute(con,slate,DATE,'CONFIRMED',now=now)
    assert result['card'] is None and not result['errors']
    assert result['frozenCardContinuation']['newCardIssued'] is False
    result['gateCertification']=certify_gates(con,DATE,'CONFIRMED',result['games'])
    export_dashboard(con,DATE,'CONFIRMED',slate,tmp_path)
    status=export_run(con,DATE,'CONFIRMED',result,tmp_path)
    assert status['publicationDecision']=='FROZEN_CORE_REVALIDATED_UNSTARTED_RECIPIENTS',status
    verified=verify_published_core(tmp_path,DATE)
    assert verified['frozenLegs']==1 and verified['unstartedLegsRevalidated']==2
    assert get_card(con,DATE)==before
    assert (tmp_path/'site_cards'/f'{DATE}.json').read_bytes()==saved
    assert con.execute("SELECT COUNT(*) FROM gates WHERE gate='G18' AND disposition='PASS'").fetchone()[0]==0
    # A failed future recipient cannot borrow its old pregame certificate.
    leg=before['current_legs'][1]
    con.execute("UPDATE gates SET disposition='NOT_EXECUTED' WHERE game_id=? AND player_id=? AND gate='G6'",(leg['gameId'],leg['playerId']))
    status=export_run(con,DATE,'CONFIRMED',result,tmp_path)
    assert status['selectedCoreFullyCertified'] is False
    with pytest.raises(AssertionError):verify_published_core(tmp_path,DATE)
    assert get_card(con,DATE)==before
    con.close()


def test_identical_gate_payloads_keep_each_original_execution_cohort(tmp_path):
    from nhl_true_blender_engine.storage import save_gates
    con=open_db(str(tmp_path/'cohorts.sqlite'))
    rows=[{'gameId':'g1','playerId':'p1','gate':g,'disposition':'PASS',
        'details':{'executionIndex':i}} for i,g in enumerate(
        __import__('nhl_true_blender_engine.engine',fromlist=['EXECUTION_ORDER']).EXECUTION_ORDER)]
    times=[datetime.fromisoformat(f'2026-11-19T{hour}:00:00+00:00') for hour in (20,21,22)]
    for t in times:save_gates(con,DATE,'CONFIRMED',rows,now=t)
    cohorts=con.execute('SELECT evaluated_at,COUNT(*) FROM gate_history GROUP BY evaluated_at').fetchall()
    assert len(cohorts)==2 and all(r[1]==20 for r in cohorts)
    con.close()
