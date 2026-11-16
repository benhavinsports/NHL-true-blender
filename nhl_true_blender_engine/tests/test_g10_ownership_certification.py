"""G10 distinguishes historical credited goals from predicting tonight's scorer.

Regression for a real observed risk: successful assisters also have prior
goals; a sourced historical own goal must not be treated as evidence of
tonight's no-assist/finisher role.
"""
from nhl_true_blender_engine.engine import evaluate_skater
from nhl_true_blender_engine.tests.test_engine import game

def test_historical_goal_recipient_does_not_assert_future_not_feeder():
    match=game(1)
    team=match["away"]
    player=match["rosters"][team]["data"]["players"][0]
    goalie=match["goalies"][match["home"]][0]
    rivals=match["rosters"][team]["data"]["players"]
    result,rows=evaluate_skater(match,team,player,rivals,goalie,"CONFIRMED")
    g10=next(x for x in rows if x["gate"]=="G10")
    assert g10["disposition"]=="PASS"
    proof=g10["details"]["evidence"]
    assert proof["historicalDirectGoalRecipientVerified"] is True
    assert proof["directGoalProofIsHistoricalNotTonight"] is True
    assert proof["futureAssistsVsGoalRecipientUnresolved"] is True
    assert proof["futureNotAssistOrFeederProven"] is False
    assert proof.get("notAssistOrFeeder") is not True
    assert g10["details"]["sourceIds"]

def test_no_historical_direct_goal_is_not_certified_by_a_bare_recipient_boolean():
    match=game(1)
    team=match["away"]
    player=match["rosters"][team]["data"]["players"][0]
    # Independently sourced zero credited goals, including no recent goal
    # IDs. A bare boolean must not masquerade as official recipient proof.
    player["officialGoalTotal"]["data"]["goals"]=0
    player["mappedGoals"]["data"]["goals"]=[]
    player["finishOwnership"]["data"]["recipient"]=True
    goalie=match["goalies"][match["home"]][0]
    _,rows=evaluate_skater(match,team,player,
        match["rosters"][team]["data"]["players"],goalie,"CONFIRMED")
    g10=next(x for x in rows if x["gate"]=="G10")
    assert g10["disposition"]!="PASS"
    assert g10["details"]["evidence"]["futureNotAssistOrFeederProven"] is False
