"""Step 8 proves actual TEAM defensive shifts, without inventing a skater-zone match."""
from nhl_true_blender_engine.engine import (gate_record,evidence_data,receipt,
    player_releases,reconcile_logs)
from nhl_true_blender_engine.overlay_checks import independent_overlay
from nhl_true_blender_engine.tests.test_engine import game,evidence

SHIFT="https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId%3D2025020101"
PBP="https://api-web.nhle.com/v1/gamecenter/2025020101/play-by-play"

def make(player_zone="Unmapped EDGE Area",include_shift=True):
    g=game(1)
    away,home=g["away"],g["home"]
    p=g["rosters"][away]["data"]["players"][0]
    p["release"]=evidence({"archetype":"OWN_OFFICIAL_SHOT_ORIGIN",
        "zone":player_zone,"attempts":12,"ownedGoals":1})
    event={"zone":"Low Slot","gameId":"2025020101","eventId":"21",
           "period":1,"eventClock":"13:52",
           "defendingOnIcePlayerIds":["201","202","203","204","205"],
           "officialShiftChartUrl":SHIFT,"officialPlayByPlayUrl":PBP}
    g["coverage"][away]=evidence({
        "greenWeakZones":["Low Slot"],"redStrongZones":[],
        "zoneConcessions":{"Low Slot":{"shotsAgainst":27}},
        "actualDefensiveShiftMatches":1 if include_shift else 0,
        "shiftByShift":[event] if include_shift else [],
        "shiftSourceUrls":[SHIFT] if include_shift else []})
    return g,p

def review(g,p):
    goalie=g["goalies"][g["home"]][0]
    attacker=g["away"]
    rows=independent_overlay(g,attacker,p,[p],goalie,
        player_releases(p),reconcile_logs(p),[],"CONFIRMED",
        receipt,evidence_data,gate_record)
    return next(r for r in rows if r["gate"]=="Step8")

def test_true_team_shift_coverage_passes_even_if_own_edge_area_is_not_polygon_matched():
    g,p=make()
    row=review(g,p)
    assert row["disposition"]=="PASS"
    ev=row["details"]["evidence"]
    assert ev["actualShiftByShiftObserved"] is True
    assert ev["actualMatchingAreaShiftEvents"]==0
    assert ev["specificPlayerZoneShiftEvidenceProven"] is False
    assert ev["specificPlayerZoneNotAssumedFromTeamShifts"] is True
    assert ev["observedHistoricalShiftEvents"]==1
    assert SHIFT in row["details"]["sourceIds"]

def test_team_shift_review_can_succeed_with_zero_own_release_without_faking_G4():
    g,p=make()
    p["release"]=None
    row=review(g,p)
    assert row["disposition"]=="PASS"
    assert row["details"]["evidence"]["playerOwnScoringAreaNotVerified"] is True
    assert row["details"]["evidence"]["specificPlayerZoneShiftEvidenceProven"] is False

def test_without_official_shift_and_pbp_interval_proof_step8_cannot_pass():
    g,p=make(include_shift=False)
    row=review(g,p)
    assert row["disposition"]=="NOT_EXECUTED"
    assert row["details"]["evidence"]["actualShiftByShiftObserved"] is False
    assert row["details"]["evidence"]["officialShiftChartSourceCount"]==0

def test_team_only_shift_review_never_proves_a_player_scoring_lane():
    g,p=make(player_zone="Low Slot")
    row=review(g,p)
    assert row["disposition"]=="PASS"
    assert row["details"]["evidence"]["specificPlayerZoneShiftEvidenceProven"] is True
