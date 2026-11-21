"""G15 independent direct finisher identity must not duplicate G5's shot lane.

Tests use synthetic, fully dated official-source-shaped independent receipts;
they never assert or force a real NHL skater, team, game, or Core winner.
"""
import json
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE,evidence
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.semantic_certification import audit_gate

GAMELOG="https://api-web.nhle.com/v1/player/1000/game-log/20262027/2"
EDGE="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/1000/now"

def separate_finisher_scene():
    s=snapshot()
    game=s["games"][0]
    p=game["rosters"][game["away"]]["data"]["players"][0]
    pid=str(p["id"])
    gl="https://api-web.nhle.com/v1/player/"+pid+"/game-log/20262027/2"
    origin="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/"+pid+"/now"
    # Actual historical scoring owned by THIS skater in another origin,
    # but he has seven OWN on-net shots from the independently goaler-weak slot.
    # Historical exact-lane goals are ZERO, never overwritten or inferred.
    p["release"]=evidence({
        # Independent mechanism evidence is required by G4/Step7 even when
        # this test is isolating zero-goal-lane reconciliation at G15.
        "archetype":"own wrist/snap release",
        "zone":"slot","attempts":7,"ownedGoals":0,
        "sourceType":"NHL_EDGE_SHOT_ORIGIN_PEER_PERCENTILE",
        "allRoutes":[{"zone":"slot","sog":7,"ownedGoals":0},
                     {"zone":"circle","sog":14,"ownedGoals":3}],
        "canDeterminePrimary":True,
    },origin)
    p["seasonHistory"]=evidence({
        "playerId":pid,
        "sourceType":"NHL_OFFICIAL_PLAYER_DATED_REGULAR_SEASON_GAME_LOG",
        "scope":"OFFICIAL_CURRENT_SEASON_DATED_GAMES_PRIOR_TO_SLATE",
        "officialPastSeasonGoals":3,
        "goalScoringGames":[{"gameId":"2026020112","date":"2026-11-01",
                             "goals":3,"shotsOnGoal":5}],
        "sameSlateDateExcluded":True,
        "noSyntheticGoalEventIds":True,
    },gl)
    return s,game,p

def gate15(s,tmp_path):
    db=open_db(str(tmp_path/"g15.sqlite"))
    try:
        execute(db,s,DATE,"CONFIRMED")
        pid=s["games"][0]["rosters"][s["games"][0]["away"]]["data"]["players"][0]["id"]
        row=db.execute("SELECT disposition,details FROM gates WHERE game_id=? AND player_id=? AND gate='G15' AND stage='CONFIRMED'",
            (s["games"][0]["id"],str(pid))).fetchone()
        assert row is not None
        return row["disposition"],json.loads(row["details"])["evidence"]
    finally:
        db.close()

def test_real_historical_recipient_plus_exact_full_edge_goal_reconciliation_can_satisfy_g15(tmp_path):
    s,g,p=separate_finisher_scene()
    decision,ev=gate15(s,tmp_path)
    assert decision=="PASS",ev
    assert ev["officialOwnedGoalsInMatchedOrigin"]==0
    assert ev["matchedOriginOwnOnNetShots"]==7
    assert ev["officialDatedSeasonGoals"]==3
    assert ev["totalOwnedGoalsFromEveryNhlEdgeOrigin"]==3
    assert ev["fullSeasonGoalCreditsReconciledAgainstEdgeOrigins"] is True
    assert ev["matchedOriginHasHistoricalGoal"] is False
    assert ev["sameLaneGoalsNotInferredFromScoringElsewhere"] is True
    assert ev["directFinisherEvidenceMethod"].startswith("OFFICIAL_FULL_SEASON_GOALS_MATCH_")

def test_g15_declines_any_unreconciled_full_season_edge_totals(tmp_path):
    s,g,p=separate_finisher_scene()
    p["seasonHistory"]["data"]["officialPastSeasonGoals"]=4
    p["seasonHistory"]["data"]["goalScoringGames"][0]["goals"]=4
    decision,ev=gate15(s,tmp_path)
    assert decision=="NOT_EXECUTED"
    assert ev["officialOwnedGoalsInMatchedOrigin"]==0
    assert ev["fullSeasonGoalCreditsReconciledAgainstEdgeOrigins"] is False

def test_no_own_lanes_without_direct_shots_cannot_forge_g15(tmp_path):
    s,g,p=separate_finisher_scene()
    p["release"]["data"]["attempts"]=0
    p["release"]["data"]["allRoutes"][0]["sog"]=0
    decision,ev=gate15(s,tmp_path)
    assert decision=="NOT_EXECUTED"
    assert ev["fullSeasonGoalCreditsReconciledAgainstEdgeOrigins"] is False

def test_missing_independent_dated_source_cannot_certify_cross_origin_finisher(tmp_path):
    s,g,p=separate_finisher_scene()
    del p["seasonHistory"]
    decision,ev=gate15(s,tmp_path)
    assert decision=="NOT_EXECUTED"
    assert ev["officialDatedSeasonGoals"] is None

def test_g15_semantic_auditor_rejects_manufactured_non_lane_goals():
    good={"independentHistoricalGoalFinishingEvidence":True,
        "separateOfficialShotOriginSource":True,
        "officialOwnedGoalsInMatchedOrigin":0,
        "matchedOriginOwnOnNetShots":7,"matchedOriginHasHistoricalGoal":False,
        "officialDatedSeasonGoals":3,"totalOwnedGoalsFromEveryNhlEdgeOrigin":3,
        "fullSeasonGoalCreditsReconciledAgainstEdgeOrigins":True,
        "sameLaneGoalsNotInferredFromScoringElsewhere":True,
        "independentSeasonLogSource":GAMELOG,
        "directFinisherEvidenceMethod":
          "OFFICIAL_FULL_SEASON_GOALS_MATCH_ALL_EDGE_OWN_ORIGINS_AND_SOURCED_MATCHED_LANE_SHOTS"}
    src=[GAMELOG,EDGE]
    assert audit_gate("G15",good,src,"CONFIRMED")==[]
    for changed in (
        {"officialOwnedGoalsInMatchedOrigin":1,"matchedOriginHasHistoricalGoal":False},
        {"matchedOriginOwnOnNetShots":0},
        {"totalOwnedGoalsFromEveryNhlEdgeOrigin":2},
        {"independentSeasonLogSource":"https://unrelated.example/other"},
        {"fullSeasonGoalCreditsReconciledAgainstEdgeOrigins":False}
    ):
        altered={**good,**changed}
        assert "G15_FINISHER_PROOF_NOT_INDEPENDENT" in audit_gate(
            "G15",altered,src,"CONFIRMED")


def test_g18_does_not_reject_a_full_g15_verified_goal_recipient_for_zero_exact_lane_goals(tmp_path):
    s,g,p=separate_finisher_scene()
    # The fixture rival independently owns scored goals from this exact
    # lane, so source-backed G10.5 would correctly reject the candidate.
    # Only mark that unrelated rival OUT to isolate the G18-to-G15 bug.
    s["games"][0]["rosters"][g["away"]]["data"]["players"][1]["availability"]="OUT"
    con=open_db(str(tmp_path/"route.sqlite"))
    try:
        result=execute(con,s,DATE,"CONFIRMED")
        rows=con.execute("""SELECT gate,disposition,details FROM gates
          WHERE game_id=? AND player_id=? AND gate IN ('G5','G10.5','G15','G17','G18')
          ORDER BY CASE gate WHEN 'G5' THEN 1 WHEN 'G10.5' THEN 2
          WHEN 'G15' THEN 3 WHEN 'G17' THEN 4 ELSE 5 END""",
          (str(g["id"]),str(p["id"]))).fetchall()
        decisions={row["gate"]:row["disposition"] for row in rows}
        assert all(decisions.get(gate)=="PASS" for gate in
            ('G5','G10.5','G15','G17','G18')),decisions
        g18=json.loads(next(row["details"] for row in rows if row["gate"]=="G18"))["evidence"]
        route=g18["pathClassificationEvidence"]
        assert route["historicMatchedLaneOwnedGoals"]==0
        assert route["G15IndependentFinisherReconciledBeyondMatchedOrigin"] is True
        assert route["neverClaimUnobservedSameLaneGoals"] is True
        assert route["positiveDirectGateEvidence"]["observedOwnOnNetShotsInSelectedLane"] is True
        assert route["positiveDirectGateEvidence"]["historicallyCreditedIndependentGoalRecipient"] is True
    finally:
        con.close()

