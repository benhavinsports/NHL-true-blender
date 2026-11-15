from nhl_true_blender_engine.engine import challenger_proof

SRC="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/"
def p(pid,zone,shots,goals,additional=None):
    areas=[{"zone":zone,"sog":shots,"ownedGoals":goals}]
    areas.extend(additional or [])
    return {"id":str(pid),"name":"Fixture "+str(pid),"availability":"PROJECTED_ACTIVE",
            "release":{"sourceUrl":SRC+str(pid)+"/now",
                       "observedAt":"2026-11-15T12:00:00Z",
                       "data":{"archetype":"OBSERVED_OWN_SHOT_ORIGIN",
                               "zone":zone,"attempts":shots,"ownedGoals":goals,
                               "allRoutes":areas}}}

def test_missing_sample_goal_log_does_not_erase_independent_same_lane_own_route():
    favorite=p(1,"Low Slot",42,7)
    rival=p(2,"High Slot",35,4,[{"zone":"Low Slot","sog":12,"ownedGoals":2}])
    yes,rows=challenger_proof(favorite,[rival],{"Low Slot":{}})
    assert yes is True
    assert rows[0]["sameLane"] is True
    assert rows[0]["status"]=="DEFEATED"
    assert rows[0]["challenger"]["shotsOnGoal"]==12
    assert rows[0]["rivalEVRole"] is None
    assert rows[0]["roleReviewIncomplete"] is True

def test_no_unjustified_transfer_if_challenger_has_more_owned_goals():
    favorite=p(1,"Low Slot",22,3)
    rival=p(2,"Low Slot",16,7)
    yes,rows=challenger_proof(favorite,[rival],{"Low Slot":{}})
    assert yes is False
    assert rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"

def test_missing_rival_release_is_not_a_false_victory():
    favorite=p(1,"Low Slot",22,3)
    rival={"id":"2","name":"Depth skater","availability":"UNVERIFIED"}
    yes,rows=challenger_proof(favorite,[rival],{"Low Slot":{}})
    assert yes is False and rows[0]["status"]=="NO_RELEASE_SOURCE"

def test_all_meaningful_challengers_have_explicit_outcomes():
    favorite=p(1,"Low Slot",30,6)
    rivals=[p(2,"High Slot",31,7),p(3,"Low Slot",9,0)]
    yes,rows=challenger_proof(favorite,rivals,{"Low Slot":{}})
    assert yes and len(rows)==2
    assert [x["status"] for x in rows]==["DIFFERENT_TARGET_LANE","DEFEATED"]
