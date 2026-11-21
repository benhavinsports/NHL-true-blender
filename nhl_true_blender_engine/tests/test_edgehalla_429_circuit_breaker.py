"""A provider's 429 must not trigger a 28-team request storm or a false G6 PASS."""
import pytest
from nhl_true_blender_engine import edgehalla_deployment as edge


@pytest.mark.asyncio
async def test_edgehalla_429_is_circuit_breaker_not_a_projected_lineup(monkeypatch):
    requests=[]
    class Response:
        status_code=429
        text="<h1>Untrusted previous-game lineup</h1>"
    class Client:
        def __init__(self,*args,**kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self,*args):
            pass
        async def get(self,url):
            requests.append(url)
            return Response()
    monkeypatch.setattr(edge.httpx,"AsyncClient",Client)
    snapshot={"games":[{"id":"1","away":"EDM","home":"CAR"},
                       {"id":"2","away":"CHI","home":"CGY"},
                       {"id":"3","away":"PIT","home":"NSH"}]}
    class UnusedDB:
        def execute(self,*args,**kwargs):
            raise AssertionError("429 may not be used to create role evidence")
    result=await edge.collect_edgehalla_deployment(
        UnusedDB(),snapshot,"2026-11-21","PROJECTED")
    assert result["deploymentRecords"]==0
    assert len(requests)<=2
    assert len(result["teams"])==6
    assert all(r["status"]=="SOURCE_UNAVAILABLE" for r in result["teams"])
    assert all("429" in r["reason"] for r in result["teams"])
