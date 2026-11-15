from nhl_true_blender_engine.engine import release_matched_to_g0_target
SRC="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/99/now"

def player():
    return {"id":"99","name":"Skater","release":{
        "sourceUrl":SRC,"observedAt":"2026-11-15T13:00:00Z",
        "data":{"archetype":"OBSERVED_OWN_SHOT_ORIGIN",
            "zone":"High Slot","attempts":30,"ownedGoals":5,
            "allRoutes":[{"zone":"High Slot","sog":30,"ownedGoals":5},
                         {"zone":"Low Slot","sog":18,"ownedGoals":4},
                         {"zone":"R Circle","sog":26,"ownedGoals":3}]}}}
def test_use_actual_own_secondary_route_only_after_g0_goalie_weakness_is_identified():
    p=player()
    g={"data":{"weakZones":{"Low Slot":{"shotsAgainst":60}},
               "goalieId":"88","status":"EXPECTED"}}
    matched=release_matched_to_g0_target(p,g)
    assert matched["release"]["data"]["zone"]=="Low Slot"
    assert matched["release"]["data"]["attempts"]==18
    assert matched["release"]["data"]["ownedGoals"]==4
    assert matched["release"]["data"]["originalPrimaryOrigin"]=="High Slot"
    assert matched["release"]["data"]["anatomicalPlacementCertified"] is False
    assert p["release"]["data"]["zone"]=="High Slot"
def test_distinct_goalie_weakness_reselects_independent_g5_route_not_original_mutation():
    p=player()
    g={"data":{"weakZones":{"R Circle":{"shotsAgainst":60}},
               "goalieId":"77","status":"CONFIRMED"}}
    matched=release_matched_to_g0_target(p,g)
    assert matched["release"]["data"]["zone"]=="R Circle"
    assert matched["release"]["data"]["ownedGoals"]==3
    assert p["release"]["data"]["zone"]=="High Slot"
def test_unknown_weakness_never_fabricates_route():
    p=player()
    assert release_matched_to_g0_target(p,{"data":{"weakZones":{}}}) is p
