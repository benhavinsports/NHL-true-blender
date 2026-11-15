"""Rare real NHL shot origins must not disappear behind the first 180 shifts."""
import asyncio
from nhl_true_blender_engine import shift_coverage

class FakeResponse:
    def raise_for_status(self):return None
    def json(self):
        return {"data":[{
            "gameId":2025020101,"typeCode":517,"teamId":102,
            "playerId":player,"period":1,"startTime":"00:00",
            "endTime":"20:00"}
            for player in (201,202,203,204,205)]}

class FakeClient:
    def __init__(self,*args,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*exc):return None
    async def get(self,url):
        assert "shiftcharts" in url and "2025020101" in url
        return FakeResponse()

def test_late_rare_real_circle_origin_kept_and_not_invented(monkeypatch):
    monkeypatch.setattr(shift_coverage.httpx,"AsyncClient",FakeClient)
    ev=[]
    for i in range(210):
        ev.append({"gameId":"2025020101","eventId":str(i),
            "type":"shot-on-goal","ownerTeamId":"101","period":1,
            "timeInPeriod":"07:00",
            "x":64 if i==209 else 83,
            "y":22 if i==209 else 2,
            "sourceUrl":"https://api-web.nhle.com/v1/gamecenter/2025020101/play-by-play"})
    games={"2025020101":{"homeTeamId":"101","awayTeamId":"102"}}
    result=asyncio.run(shift_coverage.collect_shift_coverage(
        {"2025020101":"2025-10-21"},ev,games))
    assert result["chartedGames"]==1
    assert result["matchedDefensiveShotEvents"]==210
    defense=result["byDefendingTeamId"]["102"]
    rare=[e for e in defense["sampleEvents"] if e["zone"]=="L Circle"]
    assert len(rare)==1
    assert rare[0]["eventId"]=="209"
    assert rare[0]["defendingOnIcePlayerIds"]==["201","202","203","204","205"]
    assert "nhle.com/stats/rest/en/shiftcharts" in rare[0]["officialShiftChartUrl"]
    assert len([e for e in defense["sampleEvents"] if e["zone"]=="Low Slot"])==16
    assert defense["zoneEvents"]["L Circle"]==1
    assert defense["zoneEvents"]["Low Slot"]==209
    assert result["doesNotConfirmTonightLines"] is True
    assert result["doesNotProveGloveBlockerOrFiveHole"] is True
