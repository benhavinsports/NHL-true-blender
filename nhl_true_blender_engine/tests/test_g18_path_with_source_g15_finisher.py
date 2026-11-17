"""Source-grounded pre-Core path after G15 independent historical finisher proof.

No score guess, no forced PRIMARY/TRANSFER/WHO quotas or invented same-lane
historical goals. All twenty original gate functions remain independently run.
"""
import json
from nhl_true_blender_engine.engine import (
    adjudicate_scoring_path,execute)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import (
    evidence,snapshot,DATE)

SRC="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/8485366/now"
LOG="https://api-web.nhle.com/v1/player/8485366/game-log/20262027/2"

def source_scene():
    release={"zone":"R Point","originalPrimaryOrigin":"R Circle",
        "attempts":7,"ownedGoals":0,"archetype":"OBSERVED_OWN_SHOT_ORIGIN",
        "allRoutes":[{"zone":"R Point","sog":7,"ownedGoals":0},
                     {"zone":"R Circle","sog":11,"ownedGoals":2},
                     {"zone":"L Circle","sog":13,"ownedGoals":1},
                     {"zone":"Low Slot","sog":4,"ownedGoals":1},
                     {"zone":"Center Point","sog":9,"ownedGoals":1},
                     {"zone":"L Net Side","sog":1,"ownedGoals":1}]}
    player={"id":"8485366","name":"Synthetic Source-Verified Recipient",
      "release":evidence(release,source=SRC),
      "finishOwnership":evidence({"recipient":True,"creditedGoalsVerified":True}),
      "seasonHistory":evidence({"officialPastSeasonGoals":6},source=LOG),
      "deployment":evidence({"EV":"D1","PP":"PP2","status":"PROJECTED"})}
    goalie=evidence({"weakZones":{"R Point":{"shotsAgainst":23,"goalsAgainst":1}},
             "goalieId":"8475660","status":"CONFIRMED"})
    coverage=evidence({"greenWeakZones":["R Point"],"redStrongZones":[]})
    proof={"independentHistoricalGoalFinishingEvidence":True,
      "separateOfficialShotOriginSource":True,
      "fullSeasonGoalCreditsReconciledAgainstEdgeOrigins":True,
      "officialOwnedGoalsInMatchedOrigin":0,
      "matchedOriginOwnOnNetShots":7,
      "matchedOriginHasHistoricalGoal":False,
      "officialDatedSeasonGoals":6,"totalOwnedGoalsFromEveryNhlEdgeOrigin":6,
      "sameLaneGoalsNotInferredFromScoringElsewhere":True,
      "directFinisherEvidenceMethod":
        "OFFICIAL_FULL_SEASON_GOALS_MATCH_ALL_EDGE_OWN_ORIGINS_AND_SOURCED_MATCHED_LANE_SHOTS",
      "independentSeasonLogSource":LOG}
    gates={g:{"disposition":"PASS","details":{}} for g in (
        "G0","G3","G4","G5","G6","G7","G9","G10","G10.5",
        "G12","G15","G16","G17")}
    gates["G15"]["details"]=proof
    return player,release,goalie,coverage,gates

def route(player,release,goalie,coverage,gates):
    return adjudicate_scoring_path(player,[player],release,goalie,coverage,
        gates,[],False)

def test_cross_origin_finisher_plus_real_shots_can_qualify_source_derived_transfer():
    p,rel,g,c,d=source_scene()
    path,proof=route(p,rel,g,c,d)
    assert path=="TRANSFER",proof
    direct=proof["positiveDirectGateEvidence"]
    assert direct["G0ThruG17SourcePass"] is True
    assert direct["historicallyCreditedIndependentGoalRecipient"] is True
    assert direct["independentlyReconciledOwnFinisherWithRealTargetLaneShots"] is True
    assert direct["observedOwnedGoalsInSelectedLane"] is False
    assert proof["laneChangedAfterGoalieFirstG0"] is True
    assert proof["pathQuotaApplied"] is False
    assert "ZERO historically credited goals" in proof["rationale"]

def test_primary_label_requires_source_primary_not_goalie_retargeted_lane():
    p,rel,g,c,d=source_scene()
    rel["originalPrimaryOrigin"]="R Point"
    path,proof=route(p,rel,g,c,d)
    assert path=="PRIMARY"
    assert proof["primaryOriginIsSourceDistinct"] is True
    assert proof["fallbackToPrimary"] is False

def test_fake_goal_finisher_or_missing_real_target_shots_never_has_a_path():
    for key,new_value in [
       ("fullSeasonGoalCreditsReconciledAgainstEdgeOrigins",False),
       ("totalOwnedGoalsFromEveryNhlEdgeOrigin",5),
       ("independentSeasonLogSource","https://not-the-official-log.example/a"),
       ("matchedOriginOwnOnNetShots",0),
       ("sameLaneGoalsNotInferredFromScoringElsewhere",False),
    ]:
        p,rel,g,c,d=source_scene()
        d["G15"]["details"][key]=new_value
        label,proof=route(p,rel,g,c,d)
        assert label is None,(key,label,proof)
        assert proof["unknownIsNotAPath"] is True

def test_changed_origin_loses_classification_if_rival_or_goalie_not_supported():
    p,rel,g,c,d=source_scene()
    for gate in ("G0","G5","G9","G10.5","G17"):
        hacked=dict(d)
        hacked[gate]={"disposition":"NOT_EXECUTED","details":{}}
        label,proof=route(p,rel,g,c,hacked)
        assert label is None,(gate,label)
    p,rel,g,c,d=source_scene()
    g["data"]["weakZones"]={}
    label,_=route(p,rel,g,c,d)
    assert label is None

def test_full_original_engine_recognizes_precore_route_without_a_historical_goal_in_that_lane(tmp_path):
    snap=snapshot(3)
    game=snap["games"][0]
    main=game["rosters"][game["away"]]["data"]["players"][0]
    # The original G0 chooses the synthetic weak 'slot'; main has actual
    # shots there but historically owns goals only from another area.
    main["release"]["data"]={
        "archetype":"OBSERVED_OWN_SHOT_ORIGIN",
        "zone":"slot","attempts":7,"ownedGoals":0,
        "sourceType":"NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE",
        "originalPrimaryOrigin":"circle",
        "allRoutes":[{"zone":"slot","sog":7,"ownedGoals":0},
                     {"zone":"circle","sog":14,"ownedGoals":3}],
        "canDeterminePrimary":True}
    main["release"]["sourceUrl"]=SRC
    main["seasonHistory"]=evidence({
        "officialPastSeasonGoals":3,
        "sourceType":"NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG",
        "goalScoringGames":[{"gameId":"2026020112","date":"2026-11-01",
                              "goals":3,"shotsOnGoal":5}],
        "scope":"OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE",
        "sameSlateDateExcluded":True},source=LOG)
    rival=game["rosters"][game["away"]]["data"]["players"][1]
    rival["release"]["data"]["zone"]="point"
    rival["release"]["data"]["ownedGoals"]=0
    rival["release"]["data"]["attempts"]=5
    # G0+G5 support 'slot' only; verified rival shoots from another lane.
    con=open_db(str(tmp_path/"original.sqlite"))
    try:
        result=execute(con,snap,DATE,"PROJECTED")
        entry=next(x for x in result["gameSurvivorPool"] if x["gameId"]==game["id"])
        assert entry["status"]=="SURVIVOR",entry
        assert entry["survivor"]["playerId"]==str(main["id"])
        assert entry["survivor"]["routeLabel"]=="TRANSFER"
        rows=con.execute("SELECT gate,disposition,details FROM gates "
           "WHERE slate_date=? AND game_id=? AND player_id=? ORDER BY rowid",
           (DATE,game["id"],str(main["id"]))).fetchall()
        assert len(rows)==20
        assert all(x["disposition"]=="PASS" for x in rows if x["gate"]!="G18")
        g15=json.loads(next(x["details"] for x in rows if x["gate"]=="G15"))["evidence"]
        assert g15["officialOwnedGoalsInMatchedOrigin"]==0
        assert g15["fullSeasonGoalCreditsReconciledAgainstEdgeOrigins"] is True
    finally:
        con.close()
