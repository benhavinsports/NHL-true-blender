"""Executable integrated contract: G0 direction -> full skater gates -> one card -> official grade.
Synthetic evidence tests the algorithm; it does NOT certify live data availability.
"""
from datetime import datetime, timedelta, timezone
from nhl_true_blender_engine.engine import execute, MASTER, OVERLAY
from nhl_true_blender_engine.storage import open_db, get_card, grade_frozen_card

SRC = "https://example.org/synthetic-contract-evidence"
DATE = (datetime.now(timezone.utc) + timedelta(days=15)).date().isoformat()
START = (datetime.now(timezone.utc) + timedelta(days=15)).isoformat()

def ev(data,source=SRC):
    return {"sourceUrl": source, "observedAt": "2026-11-15T12:00:00Z", "data": data}

def player(pid, attempts, goals):
    return {
        "id": str(pid), "name": "Test "+str(pid), "position": "C",
        "availability": "CONFIRMED", "jersey": 18,
        "release": ev({"archetype": "wrist", "zone": "slot", "attempts": attempts, "ownedGoals": goals},SRC+"/shot-origin/"+str(pid)),
        "deployment": ev({"EV": "EV2", "PP": "PP2", "status": "CONFIRMED"}),
        "gameLog": ev({"appearances": [
            {"date": "2026-11-01", "shots": attempts},
            {"date": "2026-11-02", "shots": 1}]}),
        "mappedGoals": ev({"goals": [{"goalId": str(pid)+":"+str(i), "date": "2026-11-01", "sourceUrl": SRC} for i in range(goals)]}),
        "officialGoalTotal": ev({"goals": goals}),
        "finishOwnership": ev({"recipient": True, "creditedGoalsVerified": True}),
        "pressure": ev({"recentAppearanceShots": [attempts, 1],
            "appearances": [{"date": "2026-11-01"}, {"date": "2026-11-02"}],
            "evidenceType": "OFFICIAL_HISTORICAL_SHOT_EVENTS"}),
        "contradictions": ev({"sourceType":"FIXTURE_STRUCTURED_G17",
            "unresolved":False,"anatomicalWeaknessCertified":True,
            "goalieStrengthReview":{"matchedWeakAreas":1,"strongerAreaContradiction":False},
            "lineupDisagreementReview":{"isTrulyConfirmed":True,
               "hasProjectedOrConfirmedRole":True},
            "strongestRivalReview":{"everyRivalReviewed":True,
               "eachSameLaneDefeated":True}})
    }

def fixture(n=3):
    games=[]
    for i in range(n):
        away,home="A"+str(i),"H"+str(i)
        # Both goalies have independently reviewed, measured origins.
        # G0 must select by comparable peer vulnerability, not by the count
        # or presence/absence of weak-zone labels.
        goalie=ev({"goalieId": "GH"+str(i), "team": home, "status": "CONFIRMED",
                   "weakZones": {"slot": {"shotsAgainst": 50, "goalsAgainst": 8,
                                          "leagueSavePctgPercentile": .05}},
                   "strengthZones": {"point": {"sample": 200}},
                   "sample": {"shots": 200}, "counterevidence": {"reviewed": True},
                   "sourceClass": "DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"})
        shift_url="https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId%3D2026020300"
        shift_evidence={"shiftByShift":[{
             "zone":"slot","gameId":"2026020300","eventId":"11",
             "period":1,"eventClock":"04:12",
             "defendingOnIcePlayerIds":["11","22","33"],
             "officialPlayByPlayUrl":"https://api-web.nhle.com/v1/gamecenter/2026020300/play-by-play",
             "officialShiftChartUrl":shift_url}],
             "shiftSourceUrls":[shift_url],"actualDefensiveShiftMatches":1}
        no_weak_goalie=ev({
            "goalieId":"GA"+str(i),"team":away,"status":"CONFIRMED",
            "weakZones":{"point":{"shotsAgainst":70,"goalsAgainst":1,
                                  "leagueSavePctgPercentile":.95}},
            "strengthZones":{"slot":{"shotsAgainst":70,"goalsAgainst":1}},
            "observedAreas":{"slot":{"shotsAgainst":70,"goalsAgainst":1,"saves":69}},
            "sample":{"allZoneObservations":70},"sourceReviewed":True,
            "counterevidence":{"reviewedPeerSample":True},
            "sourceClass":"DERIVED_RINK_ORIGIN_NOT_ANATOMICAL"})
        games.append({
            "id": str(9000+i), "date": DATE, "away": away, "home": home,
            "startUTC": START, "gameState": "FUT",
            "goalies": {away: [no_weak_goalie], home: [goalie]},
            "rosters": {away: ev({"players": [player(100+i*10, 30, 3), player(101+i*10, 10, 1)]}),
                        home: ev({"players": [player(102+i*10, 1, 0)]})},
            "context": ev({"venue": home, "rest": "verified"}),
            "coverage": {away: ev({
                "greenWeakZones":["slot"],"redStrongZones":["point"],
                "sourceType":"OFFICIAL_HISTORICAL_NHL_PLAY_BY_PLAY",
                "comparison":"RECENT_OPPONENT_SHOT_ATTEMPT_ORIGIN_RATE_PER_GAME_VS_OTHER_TEAM_MEDIAN",
                "lowShotVolumeIsNotEvidenceOfDefensiveStrength":True,
                "zoneConcessions":{"slot":{
                    "attemptsAgainst":24,"gameCount":8,"peerTeamsCompared":8,
                    "attemptsPerGame":3.0,"peerMedianAttemptsPerGame":1.5}},
                **shift_evidence})}
        })
    return {"games": games}

def test_full_g0_to_g18_card_and_postgame_grade(tmp_path):
    con=open_db(str(tmp_path/"integrated.sqlite"))
    try:
        result=execute(con,fixture(),DATE,"CONFIRMED")
        assert result["card"] is not None, result["errors"]
        assert result["g0Directions"] == 6
        assert result["eligibleSkaterRows"] == 6
        assert result["gateRows"] == 6*len(MASTER)+6
        legs=result["card"]["current_legs"]
        assert len(legs)==3 and len({x["gameId"] for x in legs})==3
        assert {x["playerId"] for x in legs}=={"100","110","120"}
        assert all(x["path"]=="PRIMARY" for x in legs)
        assert get_card(con,DATE)["revision"]==1
        again=execute(con,fixture(),DATE,"CONFIRMED")
        assert again["card"]["revision"]==1
        counts={(x["gameId"],x["playerId"]):1 for x in legs}
        grade=grade_frozen_card(con,DATE,counts,[SRC],True)
        assert grade["result"]=="WIN"
    finally:
        con.close()

def test_no_card_without_g0_attack_side(tmp_path):
    con=open_db(str(tmp_path/"missing.sqlite"))
    try:
        data=fixture()
        data["games"][0]["goalies"]["H0"]=[]
        result=execute(con,data,DATE,"CONFIRMED")
        assert result["card"] is None
        assert get_card(con,DATE) is None
    finally:
        con.close()
