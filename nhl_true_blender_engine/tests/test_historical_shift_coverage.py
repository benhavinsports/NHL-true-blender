"""Free NHL Stats shifts are real historical on-ice observations, not fabricated green zones."""
from datetime import datetime,timezone
import httpx
import pytest
from nhl_true_blender_engine.shift_coverage import (
    BASE,parse_shifts,period_seconds,collect_shift_coverage)
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE

def interval(pid,start="00:00",end="00:50",team=22,period=1):
    return {"gameId":1234,"teamId":team,"playerId":pid,"typeCode":517,
            "startTime":start,"endTime":end,"period":period}

def test_official_shift_feed_filters_invalid_interval_and_does_not_invent():
    rows,bad=parse_shifts({"data":[interval(101),interval(102,end="00:00"),
                                   {"gameId":1234,"typeCode":518},
                                   interval(103,start="xx:yy")]},1234)
    assert len(rows)==1
    assert bad==2
    assert rows[0]["playerId"]=="101"
    assert period_seconds("04:09")==249
    assert period_seconds("99:99") is None
    assert period_seconds(None) is None

@pytest.mark.asyncio
async def test_join_shift_clock_to_actual_opponent_shot_event(monkeypatch):
    genuine=httpx.AsyncClient
    def fake_client(*args,**kwargs):
        def handler(req):
            assert req.url.host=="api.nhle.com"
            return httpx.Response(200,json={"data":[
                interval(101),interval(102),interval(103)]})
        return genuine(*args,transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr("nhl_true_blender_engine.shift_coverage.httpx.AsyncClient",fake_client)
    urls="https://api-web.nhle.com/v1/gamecenter/1234/play-by-play"
    e={"gameId":"1234","date":"2026-11-14","type":"shot-on-goal",
       "eventId":"8","ownerTeamId":"11","period":1,"timeInPeriod":"00:25",
       "x":64,"y":22,"sourceUrl":urls}
    after={**e,"eventId":"9","timeInPeriod":"00:50"}
    out=await collect_shift_coverage({"1234":"2026-11-14"},[e,after],
          {"1234":{"homeTeamId":"11","awayTeamId":"22"}})
    assert out["chartedGames"]==1
    assert out["sampledOfficialIntervals"]==3
    defender=out["byDefendingTeamId"]["22"]
    assert defender["matchedEvents"]==1
    assert defender["unmatchedEvents"]==1
    assert defender["zoneEvents"]["L Circle"]==1
    proof=next(z for z in defender["sampleEvents"] if z["zone"]=="L Circle")
    assert proof["defendingOnIcePlayerIds"]==["101","102","103"]
    assert proof["officialShiftChartUrl"]==BASE+"1234"
    assert proof["officialPlayByPlayUrl"]==urls
    assert out["doesNotConfirmTonightLines"] is True

def test_step8_team_shift_review_has_real_clock_joined_events_and_lane_truth(tmp_path):
    games=snapshot()
    source="https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId%3D2026020300"
    for game in games["games"]:
        attack=game["away"]
        cov=game["coverage"][attack]["data"]
        cov["shiftSourceUrls"]=[source]
        cov["actualDefensiveShiftMatches"]=1
        cov["shiftByShift"]=[{"zone":"slot","gameId":"2026020300",
             "eventId":"11","period":1,"eventClock":"04:12",
             "defendingOnIcePlayerIds":["11","22","33"],
             "officialPlayByPlayUrl":"https://api-web.nhle.com/v1/gamecenter/2026020300/play-by-play",
             "officialShiftChartUrl":source}]
    con=open_db(str(tmp_path/"shift.sqlite"))
    result=execute(con,games,DATE,"CONFIRMED")
    assert result["card"] is not None,result["errors"]
    audit=certify_gates(con,DATE,"CONFIRMED",3)
    assert audit["allOverlayStepsWereIndependentlyChecked"] is True
    assert audit["selectedMasterGatesAllPass"] is True
    assert audit["selectedOverlayGatesAllPass"] is True
    assert audit["fullIndependentCardCertification"] is True
    for leg in result["card"]["current_legs"]:
        row=con.execute("""SELECT details FROM gates WHERE slate_date=? AND stage=?
            AND game_id=? AND player_id=? AND gate='Step8'""",
            (DATE,"CONFIRMED",str(leg["gameId"]),str(leg["playerId"]))).fetchone()
        import json
        payload=json.loads(row["details"])["evidence"]
        assert payload["observedHistoricalShiftEvents"]==1
        assert payload["specificPlayerZoneShiftEvidenceProven"] is True
        assert payload["historicalShiftsNotTonightLineupConfirmation"] is True
    con.close()
