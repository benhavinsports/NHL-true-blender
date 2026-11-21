"""Dated Daily Faceoff page parsing supplies projected EV pairs without post-puck reuse."""
import json

import pytest
import deployment_sources as providers
from nhl_true_blender_engine.lineup_parser import (
    dated_deployment_row, fetch_and_ingest_additional_deployment)
from nhl_true_blender_engine.storage import open_db

DATE="2026-11-21"
ASOF="2026-11-21T04:01:23.249000+00:00"
START="2026-11-21T23:00:00Z"


def _page():
    forwards=[f"Forward {i}" for i in range(1,13)]
    defense=[f"Defense {i}" for i in range(1,7)]
    pp1=[f"PP One {i}" for i in range(1,6)]
    pp2=[f"PP Two {i}" for i in range(1,6)]
    links=lambda names:"".join(
        f'<a href="/players/news/{name.lower().replace(" ","-")}/1">{name}</a>'
        for name in names)
    return (
        f"<p>Last updated: {ASOF.replace('+00:00','Z')}</p>"
        f"<h2>Forwards</h2>{links(forwards)}"
        f"<h2>Defensive Pairings</h2>{links(defense)}"
        f"<h2>1st Powerplay Unit</h2>{links(pp1)}"
        f"<h2>2nd Powerplay Unit</h2>{links(pp2)}"
        f"<h2>Goalies</h2><a href='/players/news/goalie/1'>Not a skater</a>"
    )


def test_dailyfaceoff_parser_reads_dated_forward_lines_pairs_and_pp(monkeypatch):
    class Response:
        text=_page()
    monkeypatch.setattr(providers,"get",lambda url:Response())
    rows,meta=providers.fetch_dailyfaceoff("SJS","San Jose Sharks",DATE)
    assert meta["sourceDate"]==DATE
    assert meta["dateVerified"] is True
    assert meta["sourceAsOf"]==ASOF
    assert meta["forwardNamesParsed"]==12
    assert meta["defensePairNamesParsed"]==6
    assert meta["pp1NamesParsed"]==5
    assert meta["pp2NamesParsed"]==5
    assert next(x for x in rows if x["playerName"]=="Forward 4")["line"]==2
    assert next(x for x in rows if x["playerName"]=="Defense 3")["defensePair"]==2
    assert next(x for x in rows if x["playerName"]=="PP One 3")["powerPlayUnit"]==1
    assert next(x for x in rows if x["playerName"]=="PP Two 4")["powerPlayUnit"]==2


def test_dfo_deployment_aggregation_preserves_defense_pair_source_timestamp(monkeypatch):
    rows_fixture=[{
        "playerName":"Test Defense","defensePair":2,"powerPlayUnit":None,
        "source":"Daily Faceoff page","sourcePath":"https://www.dailyfaceoff.com/teams/sjs/line-combinations",
        "sourceDate":DATE,"dateVerified":True,"sourceAsOf":ASOF,
        "retrievedAt":ASOF,"sourceTeam":"SJS"}]
    monkeypatch.setattr(providers,"fetch_hockeyinsights",lambda *a:([],{"source":None}))
    monkeypatch.setattr(providers,"fetch_nhl_article",lambda *a:([],{"source":None}))
    monkeypatch.setattr(providers,"fetch_dailyfaceoff",lambda *a:(rows_fixture,{
        "source":"Daily Faceoff page","url":"https://www.dailyfaceoff.com/teams/sjs/line-combinations",
        "sourceDate":DATE,"dateVerified":True,"sourceAsOf":ASOF}))
    monkeypatch.setattr(providers,"fetch_web_search",lambda *a,**k:([],{"source":None}))
    rows,meta=providers.fetch_deployment("SJS","San Jose Sharks",slate_date=DATE)
    player=next(x for x in rows if x["playerName"]=="Test Defense")
    assert player["defensePair"]==2
    assert player["defensePairEvidence"][0]["sourceAsOf"]==ASOF
    assert meta["defensePairEvidenceFound"] is True


def test_dfo_pair_is_rejected_if_page_was_updated_after_puck_drop():
    row={"defensePairEvidence":[{
        "value":1,"source":"Daily Faceoff page","sourceDate":DATE,
        "dateVerified":True,"sourceAsOf":"2026-11-21T23:01:00+00:00",
        "sourceUrl":"https://www.dailyfaceoff.com/teams/sjs/line-combinations"}]}
    game={"startUTC":START}
    assert dated_deployment_row(row,DATE,game)["defensePair"] is None


@pytest.mark.asyncio
async def test_current_dfo_defense_pair_is_ingested_as_d_not_f(monkeypatch):
    rows=[{
        "playerName":"Test Defense","line":None,"defensePair":1,"powerPlayUnit":None,
        "lineEvidence":[],"defensePairEvidence":[{
            "value":1,"source":"Daily Faceoff page","sourceDate":DATE,
            "dateVerified":True,"sourceAsOf":ASOF,
            "sourceUrl":"https://www.dailyfaceoff.com/teams/sjs/line-combinations"}],
        "powerPlayEvidence":[],"conflicts":[]}]
    def fetch(team,*args,**kwargs):
        return (rows if team=="SJS" else [],{"source":"Daily Faceoff page"})
    monkeypatch.setattr(providers,"fetch_deployment",fetch)
    snapshot={"games":[{
        "id":"2026020372","away":"SJS","home":"SEA","startUTC":START,
        "rosters":{
            "SJS":{"data":{"players":[{"id":"123","name":"Test Defense","position":"D"}]}},
            "SEA":{"data":{"players":[]}}
        }
    }]}
    con=open_db(":memory:")
    try:
        report=await fetch_and_ingest_additional_deployment(con,snapshot,DATE,"PROJECTED")
        assert report["deploymentRecords"]==1
        payload=json.loads(con.execute(
            "SELECT payload FROM evidence WHERE kind='PLAYER_DEPLOYMENT'").fetchone()[0])
        assert payload["EV"]=="D1"
        assert payload["status"]=="PROJECTED"
    finally:
        con.close()


@pytest.mark.asyncio
async def test_same_player_distinct_deployment_receipts_do_not_collide(monkeypatch):
    evidence_url="https://www.dailyfaceoff.com/teams/sjs/line-combinations"
    def row(pair):
        return {
            "playerName":"Test Defense","line":None,"defensePair":pair,
            "powerPlayUnit":None,"lineEvidence":[],
            "defensePairEvidence":[{
                "value":pair,"source":"Daily Faceoff page","sourceDate":DATE,
                "dateVerified":True,"sourceAsOf":ASOF,"sourceUrl":evidence_url}],
            "powerPlayEvidence":[],"conflicts":[]}
    def fetch(team,*args,**kwargs):
        return ([row(1),row(2)] if team=="SJS" else [],{"source":"Daily Faceoff page"})
    monkeypatch.setattr(providers,"fetch_deployment",fetch)
    snapshot={"games":[{
        "id":"2026020372","away":"SJS","home":"SEA","startUTC":START,
        "rosters":{
            "SJS":{"data":{"players":[{"id":"123","name":"Test Defense","position":"D"}]}},
            "SEA":{"data":{"players":[]}}
        }
    }]}
    con=open_db(":memory:")
    try:
        report=await fetch_and_ingest_additional_deployment(con,snapshot,DATE,"PROJECTED")
        stored=con.execute(
            "SELECT evidence_id,payload FROM evidence WHERE kind='PLAYER_DEPLOYMENT'").fetchall()
        assert report["deploymentRecords"]==2
        assert len(stored)==2
        assert {json.loads(x["payload"])["EV"] for x in stored}=={"D1","D2"}
        assert len({x["evidence_id"] for x in stored})==2
    finally:
        con.close()


def test_dailyfaceoff_retries_rate_limit_with_retry_after(monkeypatch):
    calls=[]
    sleeps=[]
    class Response:
        def __init__(self,status,text="",headers=None):
            self.status_code=status
            self.text=text
            self.headers=headers or {}
        def raise_for_status(self):
            if self.status_code>=400:
                import requests
                raise requests.HTTPError(str(self.status_code))
    responses=[
        Response(429,headers={"Retry-After":"0"}),
        Response(200,text=_page()),
    ]
    def fake_get(url,**kwargs):
        calls.append(url)
        return responses.pop(0)
    monkeypatch.setattr(providers.requests,"get",fake_get)
    monkeypatch.setattr(providers.time,"sleep",lambda delay:sleeps.append(delay))
    rows,meta=providers.fetch_dailyfaceoff("SJS","San Jose Sharks",DATE)
    assert len(calls)==2
    assert sleeps==[0]
    assert meta["dateVerified"] is True
    assert any(x.get("defensePair")==1 for x in rows)
