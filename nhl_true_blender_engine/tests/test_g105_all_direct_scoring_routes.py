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
    wins,rows=challenger_proof(candidate,[rival],
        {"slot":{"savePctg":.80},"circle":{"savePctg":.81}},
        ["slot","circle"])
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


def test_missing_challenger_role_or_recipient_evidence_cannot_be_marked_defeated():
    candidate,rival=players()
    rival.pop("deployment")
    wins,rows=challenger_proof(candidate,[rival],
        {"slot":{"savePctg":.80},"circle":{"savePctg":.81}},
        ["slot","circle"])
    assert wins is False
    assert rows[0]["status"]=="UNRESOLVED_ROLE_OR_RECIPIENT_EVIDENCE"
    assert rows[0]["noMissingRolePromotedToDefeated"] is True


def test_conflicting_season_and_recent_routes_remain_unresolved():
    candidate,rival=players()
    # Season EDGE favours the rival (5 vs 3), while independent recent PBP
    # favours the candidate (6 vs 2). Neither source family may overrule the other.
    candidate["recentOrigin"]["data"]["zoneCounts"]["slot"]["ownedGoals"]=6
    candidate["recentOrigin"]["data"]["zoneCounts"]["slot"]["shotsOnGoal"]=9
    rival["recentOrigin"]["data"]["zoneCounts"]["circle"]["ownedGoals"]=2
    rival["recentOrigin"]["data"]["zoneCounts"]["circle"]["shotsOnGoal"]=8
    wins,rows=challenger_proof(candidate,[rival],
        {"slot":{"savePctg":.80},"circle":{"savePctg":.81}},
        ["slot","circle"])
    assert wins is False
    assert rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"
    assert rows[0]["independentRecentTieReview"]["seasonAndRecentEvidenceAgree"] is False


def test_season_and_recent_route_evidence_must_agree_before_defeating_challenger():
    candidate,rival=players()
    # Season and recent route evidence both favour the candidate.
    rival["release"]["data"]["ownedGoals"]=1
    rival["release"]["data"]["attempts"]=8
    rival["release"]["data"]["allRoutes"][0]["ownedGoals"]=1
    rival["release"]["data"]["allRoutes"][0]["sog"]=8
    rival["recentOrigin"]["data"]["zoneCounts"]["circle"]["ownedGoals"]=1
    rival["recentOrigin"]["data"]["zoneCounts"]["circle"]["shotsOnGoal"]=8
    wins,rows=challenger_proof(candidate,[rival],
        {"slot":{"savePctg":.80},"circle":{"savePctg":.81}},
        ["slot","circle"])
    assert wins is True
    assert rows[0]["status"]=="DEFEATED"
