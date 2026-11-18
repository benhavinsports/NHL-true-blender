from nhl_true_blender_engine.engine import challenger_proof

SRC="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/"
def p(pid,zone,shots,goals,additional=None):
    areas=[{"zone":zone,"sog":shots,"ownedGoals":goals}]
    areas.extend(additional or [])
    recent={row["zone"]:{"shotsOnGoal":row["sog"],"ownedGoals":row["ownedGoals"],
             "sourceUrls":[SRC+str(pid)+"/recent/"+row["zone"]]} for row in areas}
    return {"id":str(pid),"name":"Fixture "+str(pid),"availability":"PROJECTED_ACTIVE",
            "deployment":{"sourceUrl":SRC+str(pid)+"/deployment","observedAt":"2026-11-15T12:00:00Z",
                          "data":{"EV":"EV2","status":"PROJECTED"}},
            "finishOwnership":{"sourceUrl":SRC+str(pid)+"/finish","observedAt":"2026-11-15T12:00:00Z",
                               "data":{"recipient":goals>0,"creditedGoalsVerified":True}},
            "recentOrigin":{"sourceUrl":SRC+str(pid)+"/recent","observedAt":"2026-11-15T12:00:00Z",
                "data":{"sourceType":"OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN",
                        "scope":"RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY",
                        "rinkBinsApproximateNotNhlEdgePolygons":True,
                        "historicalOwnGoalCreditOnly":True,"zoneCounts":recent}},
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
    assert rows[0]["rivalEVRole"]["EV"]=="EV2"
    assert rows[0]["roleReviewIncomplete"] is False

def test_no_unjustified_transfer_if_challenger_has_more_owned_goals():
    favorite=p(1,"Low Slot",22,3)
    rival=p(2,"Low Slot",16,7)
    yes,rows=challenger_proof(favorite,[rival],{"Low Slot":{}})
    assert yes is False
    assert rows[0]["status"]=="RIVAL_DOMINATES"

def test_actual_direct_own_goals_outweigh_more_shots_that_are_not_goals():
    favorite=p(1,"Low Slot",22,7)
    rival=p(2,"Low Slot",41,6)
    yes,rows=challenger_proof(favorite,[rival],{"Low Slot":{}})
    assert yes is True
    assert rows[0]["status"]=="DEFEATED"
    assert rows[0]["comparisonPriority"][0]=="ownedGoalsFromSameShotOrigin"

def test_equal_owned_goals_separated_only_by_real_shot_pressure():
    favorite=p(1,"Low Slot",35,5)
    rival=p(2,"Low Slot",19,5)
    yes,rows=challenger_proof(favorite,[rival],{"Low Slot":{}})
    assert yes is True
    assert rows[0]["status"]=="DEFEATED"
    yes2,rows2=challenger_proof(rival,[favorite],{"Low Slot":{}})
    assert yes2 is False
    assert rows2[0]["status"]=="RIVAL_DOMINATES"

def test_identical_direct_owned_goal_and_shot_records_cannot_be_guessed_apart():
    favorite=p(1,"Low Slot",35,5)
    rival=p(2,"Low Slot",35,5)
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
    assert yes is False and len(rows)==2
    assert [x["status"] for x in rows]==["DIFFERENT_TARGET_LANE","UNRESOLVED_ROLE_OR_RECIPIENT_EVIDENCE"]
