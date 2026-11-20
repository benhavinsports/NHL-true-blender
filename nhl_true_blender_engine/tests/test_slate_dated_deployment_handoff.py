"""Source retrieval cannot redate a stale line or borrow another source's date."""
import json
import pytest
import deployment_sources as providers
from nhl_true_blender_engine.lineup_parser import dated_deployment_row, fetch_and_ingest_additional_deployment
from nhl_true_blender_engine.storage import open_db

DATE='2026-11-21'


def assignment(value,date=None,**extra):
    return {'value':value,'sourceDate':date,'sourceUrl':'https://nhl.com/lineup',**extra}


def test_current_line_survives_stale_disagreement_without_borrowing_pp_date():
    row={'line':None,'powerPlayUnit':1,'conflicts':[{'field':'line'}],
         'lineEvidence':[assignment(1,DATE),assignment(2,'2026-11-19')],
         'powerPlayEvidence':[assignment(1)]}
    actual=dated_deployment_row(row,DATE)
    assert actual['line']==1
    assert actual['conflicts']==[]
    assert actual['powerPlayUnit'] is None
    assert actual['powerPlayEvidence']==[]
    assert len(row['lineEvidence'])==2  # source report remains untouched


def test_same_day_conflicts_and_explicitly_unverified_dates_do_not_pass():
    assert dated_deployment_row({'lineEvidence':[assignment(1,DATE),assignment(2,DATE)]},DATE)['line'] is None
    assert dated_deployment_row({'lineEvidence':[assignment(1,DATE,dateVerified=False)]},DATE)['line'] is None
    assert dated_deployment_row({'lineEvidence':[assignment(1)]},DATE)['line'] is None


def test_fetch_keeps_provider_dates_separate(monkeypatch):
    def dated(*args):
        return [{'playerName':'Test Player','line':1,'source':'dated'}],{
            'source':'dated','url':'https://nhl.com/dated','sourceDate':DATE}
    def undated(*args):
        return [{'playerName':'Test Player','powerPlayUnit':1,'source':'undated'}],{
            'source':'undated','url':'https://nhl.com/undated','dateVerified':False}
    monkeypatch.setattr(providers,'fetch_hockeyinsights',dated)
    monkeypatch.setattr(providers,'fetch_nhl_article',undated)
    monkeypatch.setattr(providers,'fetch_dailyfaceoff',lambda *a:([],{}))
    rows,_=providers.fetch_deployment('CAR','Carolina Hurricanes')
    assert rows[0]['lineEvidence'][0]['sourceDate']==DATE
    assert rows[0]['powerPlayEvidence'][0]['sourceDate'] is None
    assert dated_deployment_row(rows[0],DATE)['powerPlayUnit'] is None


@pytest.mark.asyncio
async def test_only_current_assignment_reaches_canonical_player_evidence(monkeypatch):
    rows=[{'playerName':'Test Player','line':2,'powerPlayUnit':1,
           'lineEvidence':[assignment(1,DATE),assignment(2,'2026-11-19')],
           'powerPlayEvidence':[assignment(1)]}]
    monkeypatch.setattr(providers,'fetch_deployment',lambda *a,**k:(rows,{}))
    roster={'data':{'players':[{'id':'123','name':'Test Player','position':'C'}]}}
    snapshot={'games':[{'id':'10','away':'CAR','home':'NYR',
                        'rosters':{'CAR':roster,'NYR':{'data':{'players':[]}}}}]}
    con=open_db(':memory:')
    try:
        report=await fetch_and_ingest_additional_deployment(con,snapshot,DATE,'PROJECTED')
        assert report['deploymentRecords']==1
        payload=json.loads(con.execute("SELECT payload FROM evidence WHERE kind='PLAYER_DEPLOYMENT'").fetchone()[0])
        assert payload['EV']=='F1' and payload['status']=='PROJECTED'
        assert 'PP' not in payload
        assert payload['lineEvidence'][0]['sourceDate']==DATE
    finally:
        con.close()
