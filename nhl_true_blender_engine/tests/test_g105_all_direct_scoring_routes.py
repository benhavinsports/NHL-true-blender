"""G10.5 scans the goalie-first and defense-supported FULL recipient routes.

The old implementation ignored its goalie_weak_zones input and used only
the candidate's shooting lane to falsely defeat a better direct recipient
in a different, independently viable rink scoring area.
"""
from nhl_true_blender_engine.engine import challenger_proof
from nhl_true_blender_engine.tests.test_engine import skater

def players():
    candidate=skater(701,"slot",28,3)
    rival=skater(702,"circle",18,5)
    rival["release"]["data"]["allRoutes"]=[
        {"zone":"circle","sog":18,"ownedGoals":5},
        {"zone":"slot","sog":4,"ownedGoals":0}]
    return candidate,rival

def test_higher_direct_recipient_in_other_independently_weak_lane_not_falsely_defeated():
    candidate,rival=players()
    # Both rival routes are eligible. Circle is independently more exposed
    # TONIGHT against the goalie AND the defenders; old goal counts are not the proof.
    goalie={"slot":{"leagueSavePctgPercentile":.40,"shotsAgainst":50,"goalsAgainst":10},
            "circle":{"leagueSavePctgPercentile":.10,"shotsAgainst":55,"goalsAgainst":17}}
    exposure={"zoneConcessions":{
        "slot":{"onNetShotsPerGame":9,"peerMedianOnNetShotsPerGame":8,
                "independentOnNetConcessionReview":True,
                "positiveConcessionBases":["ON_NET_SHOTS_AGAINST_PEER"]},
        "circle":{"onNetShotsPerGame":14,"peerMedianOnNetShotsPerGame":8,
                  "independentOnNetConcessionReview":True,
                  "positiveConcessionBases":["ON_NET_SHOTS_AGAINST_PEER"]}}}
    wins,rows=challenger_proof(candidate,[rival],goalie,["slot","circle"],
                               opponent_coverage=exposure)
    assert wins is False
    assert len(rows)==1
    proof=rows[0]
    assert proof["status"]=="RIVAL_DOMINATES"
    assert proof["sameLane"] is False
    assert proof["rivalAlternateGoalieWeakLane"] is True
    assert proof["candidate"]["zone"]=="slot"
    assert proof["challenger"]["zone"]=="circle"
    assert proof["challenger"]["ownedGoals"]==5
    assert proof["sourceUrls"]

def test_other_route_must_be_defensively_verified_not_arbitrarily_promoted():
    candidate,rival=players()
    # G0 supports circle but G9 green defense does not.
    wins,rows=challenger_proof(candidate,[rival],
        {"slot":{"savePctg":.80},"circle":{"savePctg":.81}},["slot"])
    assert wins is True
    assert rows[0]["status"]=="DEFEATED"
    assert rows[0]["challenger"]["zone"]=="slot"
    assert rows[0]["goalieWeaknessAndDefenseBothRequired"] is True

def test_goalie_not_weak_in_rival_other_route_keeps_same_lane_comparison():
    candidate,rival=players()
    wins,rows=challenger_proof(candidate,[rival],{"slot":{"savePctg":.80}},
        ["slot","circle"])
    assert wins is True
    assert rows[0]["status"]=="DEFEATED"
    assert rows[0]["challenger"]["zone"]=="slot"
    assert rows[0]["rivalAlternateGoalieWeakLane"] is False

def test_uncited_different_lane_never_claims_rival_cannot_score():
    candidate,rival=players()
    rival["release"]["data"]["allRoutes"]=[
        {"zone":"outside","sog":12,"ownedGoals":4}]
    wins,rows=challenger_proof(candidate,[rival],{"slot":{"savePctg":.80}},["slot"])
    assert wins is True
    assert rows[0]["status"]=="DIFFERENT_TARGET_LANE"
    assert rows[0]["notEvidenceRivalCannotScoreTonight"] is True
