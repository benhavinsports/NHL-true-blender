"""A rival's tie between independently measured source zones cannot vanish from G10.5."""
from nhl_true_blender_engine.engine import challenger_proof,release_matched_to_g0_target
from nhl_true_blender_engine.edge_derived_routes import skater_owned_routes

SRC="https://api-web.nhle.com/v1/edge/skater-shot-location-detail/"
def wrapped(pid,data):
    return {"id":str(pid),"name":"Skater","release":{
        "sourceUrl":SRC+str(pid)+"/now","observedAt":"2026-11-15T12:00:00Z",
        "data":data}}
def test_tied_primary_rival_is_still_compared_from_verified_same_area():
    a=wrapped(1,{"zone":"Low Slot","archetype":"OBSERVED_OWN_SHOT_ORIGIN",
                 "attempts":28,"ownedGoals":7,
                 "allRoutes":[{"zone":"Low Slot","sog":28,"ownedGoals":7}]})
    b=wrapped(2,{"canDeterminePrimary":False,
                 "ambiguousRoutes":[{"zone":"Low Slot","sog":14,"ownedGoals":2},
                                    {"zone":"High Slot","sog":14,"ownedGoals":2}],
                 "allRoutes":[{"zone":"Low Slot","sog":14,"ownedGoals":2},
                              {"zone":"High Slot","sog":14,"ownedGoals":2}]})
    won,rows=challenger_proof(a,[b],{"Low Slot":{}})
    assert won is False
    assert rows[0]["status"]=="NO_DECISIVE_ROUTE_SEPARATION"
    assert rows[0]["decisionBasis"]=="UNRESOLVED_TONIGHT_RECIPIENT_MATCHUP_NO_HISTORICAL_FALLBACK"
    assert rows[0]["challenger"]["ownedGoals"]==2

def test_g0_can_expose_own_verified_secondary_lane_from_tied_primary_source():
    skater=wrapped(2,{"canDeterminePrimary":False,
                 "allRoutes":[{"zone":"Low Slot","sog":14,"ownedGoals":2},
                              {"zone":"High Slot","sog":14,"ownedGoals":2}]})
    goalie={"data":{"weakZones":{"Low Slot":{"shotsAgainst":53}}}}
    result=release_matched_to_g0_target(skater,goalie)
    assert result["release"]["data"]["zone"]=="Low Slot"
    assert result["release"]["data"]["archetype"]=="OBSERVED_OWN_SHOT_ORIGIN"
    assert result["release"]["data"]["primaryWasTiedBeforeG0"] is True
    assert "zone" not in skater["release"]["data"]
