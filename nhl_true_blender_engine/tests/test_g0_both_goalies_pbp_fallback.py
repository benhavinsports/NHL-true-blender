"""G0 must use TWO independently reviewed goalie profiles, not data absence.

All player and shot values are synthetic fixtures, never real NHL claims.
"""
import json
from copy import deepcopy
from datetime import datetime,timezone
import pytest
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.engine import execute,g0_full_slate
from nhl_true_blender_engine.tests.test_engine import game,snapshot,DATE,evidence
from nhl_true_blender_engine.goalie_history_fallback import (
    pregame_log_games,summarize_goalie_origin_pbp,
    derive_independent_pbp_goalie_profile,needs_independent_pbp)

SRC="https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play"

@pytest.fixture
def con(tmp_path):
    db=open_db(str(tmp_path/"both-goalies.sqlite"))
    yield db
    db.close()

def independent_no_weak_goalie(team):
    return evidence({
        "goalieId":"goalie-strong-"+team,"team":team,"status":"EXPECTED",
        "weakZones":{},"strengthZones":{"slot":{"savePctg":.965}},
        "sample":{"allZoneObservations":68,"qualifiedWeakZoneShots":0},
        "counterevidence":{"reviewed":["slot"],"source":SRC},
        "observedAreas":{"slot":{"shotsAgainst":68,"goalsAgainst":2,"saves":66}},
        "sourceReviewed":True,
        "sourceClass":"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL",
        "anatomicalWeaknessCertified":False
    },source=SRC)

def both_goalies_full(s):
    for g in s["games"]:
        g["goalies"][g["away"]]=[independent_no_weak_goalie(g["away"])]
    return s

def test_g0_cannot_choose_one_goalie_just_because_opposite_profile_is_missing(con):
    g=game(1)
    g["goalies"][g["away"]]=[]
    directions,notes=g0_full_slate([g],"CONFIRMED")
    assert len(directions)==2
    assert directions[0]["goalieProfileEvidenced"] is True
    assert directions[1]["goalieProfileEvidenced"] is False
    assert directions[0]["oppositeDirectionMustAlsoBeReviewed"] is True
    out=execute(con,{"games":[g]},DATE,"CONFIRMED")
    assert not out["card"]
    assert out["eligibleSkaterRows"]==3
    # A missing source must never skip the remaining gate investigations.
    # Every available goalie-specific research branch has 20 master + 16
    # independent overlay rows, with G0 nonpassing and NO published pick.
    diagnostic=con.execute("""SELECT player_id,gate,disposition,details
        FROM gates WHERE slate_date=? AND stage='CONFIRMED'
         AND player_id LIKE 'G0_RESEARCH:%'""",(DATE,)).fetchall()
    from nhl_true_blender_engine.engine import EXECUTION_ORDER
    assert len(diagnostic)==3*len(EXECUTION_ORDER)
    for pid in {x["player_id"] for x in diagnostic}:
        rows=[x for x in diagnostic if x["player_id"]==pid]
        assert sorted(x["gate"] for x in rows)==sorted(EXECUTION_ORDER)
        assert next(x for x in rows if x["gate"]=="G0")["disposition"]!="PASS"
        assert next(x for x in rows if x["gate"]=="G18")["disposition"]!="PASS"
        assert all(json.loads(x["details"])["g0ResearchOnly"] is True for x in rows)
    assert any("both attack directions REQUIRE" in msg for msg in out["errors"])

def test_independently_measured_no_weak_goalie_is_a_valid_negative_g0_review(con):
    g=game(1)
    g["goalies"][g["away"]]=[independent_no_weak_goalie(g["away"])]
    directions,notes=g0_full_slate([g],"CONFIRMED")
    assert all(d["goalieProfileEvidenced"] for d in directions)
    safe=next(d for d in directions if d["defender"]==g["away"])
    assert safe["targetGoalies"][0]["weakZones"]=={}
    assert safe["targetGoalies"][0]["profileReviewed"] is True
    out=execute(con,{"games":[g]},DATE,"CONFIRMED")
    assert out["eligibleSkaterRows"]==3
    assert not any("G0 both attack directions" in msg for msg in out["errors"])

def test_full_synthetic_three_game_card_still_generated_with_two_real_g0_direction_checks(con):
    s=both_goalies_full(snapshot(3))
    out=execute(con,s,DATE,"CONFIRMED")
    assert out["card"] is not None,out["errors"]
    assert out["g0Complete"]==6
    assert out["eligibleSkaterRows"]==9
    assert len(out["card"]["current_legs"])==3

def test_goalie_game_log_filters_same_day_and_later_without_lookahead():
    response={"data":{"gameLog":[
        {"gameId":100,"gameDate":"2026-11-15"},
        {"gameId":101,"gameDate":"2026-11-14"},
        {"gameId":102,"gameDate":"2026-11-13"},
        {"gameId":103,"gameDate":"2026-11-16"},
        {"gameId":101,"gameDate":"2026-11-14"}]}}
    assert pregame_log_games(response,"2026-11-15")==[("101","2026-11-14"),("102","2026-11-13")]

def shot(gid,event,goalie,goal):
    return {"gameId":str(gid),"eventId":str(event),"goalieId":str(goalie),
        "type":"goal" if goal else "shot-on-goal",
        "x":82,"y":4,"sourceUrl":SRC,"date":"2026-11-10"}

def test_official_goalie_pbp_peer_comparison_uses_actual_saves_goals_and_identity():
    events=[]
    for goal_id,against in [(44,8),(45,1),(46,2),(47,3),(48,4)]:
        events.extend(shot(1000+goal_id,i,goal_id,i<=against) for i in range(1,26))
    # This shot had no goalie ID; cannot be assigned to any goalie or peer.
    events.append(shot(1044,26,None,True))
    events[-1]["goalieId"]=None
    zoned=summarize_goalie_origin_pbp(events)
    assert zoned["44"]["Low Slot"]["shotsAgainst"]==25
    assert zoned["44"]["Low Slot"]["goalsAgainst"]==8
    parsed=derive_independent_pbp_goalie_profile("44",zoned)
    assert parsed["weakZones"]["Low Slot"]["goalsAgainst"]==8
    assert parsed["weakZones"]["Low Slot"]["shotsAgainst"]==25
    assert parsed["fullySourceComparedAreas"]==1
    assert parsed["weakZones"]["Low Slot"]["samplePeerSavePctgPercentile"]==0
    assert parsed["anatomicalWeaknessCertified"] is False
    assert parsed["sample"]["historicalGameIds"]==["1044"]
    assert SRC in parsed["historicalPbpSources"]

def test_sample_insufficient_does_not_certify_weakness():
    events=[shot(1001,i,44,True) for i in range(1,4)]
    prof=derive_independent_pbp_goalie_profile("44",summarize_goalie_origin_pbp(events))
    assert prof["weakZones"]=={}
    assert prof["fullySourceComparedAreas"]==0

def test_unqualified_edge_goalie_origin_triggers_independent_pbp_research():
    source={"sourceClass":"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL",
            "observedAreas":{"Low Slot":{"shotsAgainst":30}},
            "sample":{"allZoneObservations":30},
            "sourceReviewed":False,"weakZones":{}}
    # Thirty observed shots without a proven peer comparison is NOT a
    # certified G0 goalie review.
    assert needs_independent_pbp(source) is True
    source["sourceReviewed"]=True
    assert needs_independent_pbp(source) is False
    pbp={"sourceClass":"INDEPENDENT_OFFICIAL_RINK_ORIGIN_PROXY",
         "fullySourceComparedAreas":0}
    assert needs_independent_pbp(pbp) is True
    pbp["fullySourceComparedAreas"]=1
    assert needs_independent_pbp(pbp) is False

