"""A 429 gets a Retry-After-aware retry; persistent limits resume next cycle."""
import pytest
from nhl_true_blender_engine import edgehalla_deployment as edge


@pytest.mark.asyncio
async def test_edgehalla_retries_a_429_after_retry_after(monkeypatch):
    requests=[]
    html="""<html><body>
    <h1>Kings Line Combinations Today</h1>
    <p>Updated Nov 19, 6:31 AM ET</p>
    <p>Projected for the next game</p>
    </body></html>"""
    class Response:
        def __init__(self,status,text="",headers=None):
            self.status_code=status
            self.text=text
            self.headers=headers or {}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")
    responses=[Response(429,headers={"Retry-After":"1"}),
               Response(200,html),Response(200,html)]
    class Client:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url):
            requests.append(url)
            return responses.pop(0)
    async def no_sleep(_seconds): pass
    monkeypatch.setattr(edge.httpx,"AsyncClient",Client)
    monkeypatch.setattr(edge.asyncio,"sleep",no_sleep)
    class Cursor:
        def fetchone(self): return None
    class DB:
        def execute(self,*args,**kwargs): return Cursor()
    snapshot={"games":[
        {"id":"1","away":"LAK","home":"CAR","rosters":{"LAK":{"data":{"players":[]}},"CAR":{"data":{"players":[]}}}}
    ]}
    result=await edge.collect_edgehalla_deployment(
        DB(),snapshot,"2026-11-19","PROJECTED")
    assert requests[0] == requests[1]
    assert len(requests)==3
    assert result["deploymentRecords"]==0
    assert all(row["status"]!="SOURCE_UNAVAILABLE" for row in result["teams"])
    assert all("NO_RETRY" not in str(row.get("reason")) for row in result["teams"])


@pytest.mark.asyncio
async def test_persistent_edgehalla_429_is_retried_then_resumed_next_cycle(monkeypatch):
    requests=[]
    class Response:
        status_code=429
        text=""
        headers={"Retry-After":"0"}
    class Client:
        def __init__(self,*args,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url):
            requests.append(url)
            return Response()
    async def no_sleep(_seconds): pass
    monkeypatch.setattr(edge.httpx,"AsyncClient",Client)
    monkeypatch.setattr(edge.asyncio,"sleep",no_sleep)
    snapshot={"games":[{"id":"1","away":"EDM","home":"CAR"},
                       {"id":"2","away":"CHI","home":"CGY"},
                       {"id":"3","away":"PIT","home":"NSH"}]}
    class UnusedDB:
        def execute(self,*args,**kwargs):
            raise AssertionError("429 may not create role evidence")
    result=await edge.collect_edgehalla_deployment(
        UnusedDB(),snapshot,"2026-11-21","PROJECTED")
    assert result["deploymentRecords"]==0
    assert len(requests)==2
    assert len(result["teams"])==6
    assert all(r["status"]=="SOURCE_UNAVAILABLE" for r in result["teams"])
    assert all("SOURCE_RATE_LIMITED_RETRY_NEXT_CYCLE" in r["reason"]
               for r in result["teams"])
