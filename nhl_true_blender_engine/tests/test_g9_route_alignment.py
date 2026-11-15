"""G0 first, G5 release route and independent G9 opponent area must agree."""
from nhl_true_blender_engine.engine import release_matched_to_g0_target

S="https://api-web.nhle.com/v1"
def source(data,url):
    return {"sourceUrl":url,"observedAt":"2026-11-15T12:00:00+00:00","data":data}
def shooter():
    return {"id":"99","release":source({
        "archetype":"OBSERVED_OWN_SHOT_ORIGIN","zone":"Low Slot",
        "attempts":42,"ownedGoals":7,
        "allRoutes":[{"zone":"Low Slot","sog":42,"ownedGoals":7},
                     {"zone":"L Circle","sog":25,"ownedGoals":4},
                     {"zone":"High Slot","sog":18,"ownedGoals":2}]},
        S+"/edge/skater-shot-location-detail/99/now")}
def goalie():
    return source({"weakZones":{"Low Slot":{"shotsAgainst":60},
                                "L Circle":{"shotsAgainst":42}}},S+"/edge/goalie-shot-location-detail/88/now")
def defense(green):
    return source({"greenWeakZones":green,"redStrongZones":["Low Slot"] if "Low Slot" not in green else []},
                  S+"/gamecenter/1234/play-by-play")

def test_g9_proven_l_circle_secondary_route_not_lost_at_g5():
    p=shooter(); g=goalie(); c=defense(["L Circle"])
    matched=release_matched_to_g0_target(p,g,c)
    assert matched["release"]["data"]["zone"]=="L Circle"
    assert matched["release"]["data"]["ownedGoals"]==4
    assert matched["release"]["data"]["g9DefensiveLaneIndependentlyMatched"] is True
    assert matched["release"]["data"]["g9CoverageSourceUrl"]==c["sourceUrl"]
    assert p["release"]["data"]["zone"]=="Low Slot"

def test_no_g9_green_match_never_claims_fake_defense_support():
    p=shooter(); g=goalie()
    matched=release_matched_to_g0_target(p,g,defense(["High Slot"]))
    assert matched["release"]["data"]["zone"]=="Low Slot"
    assert matched["release"]["data"]["g9DefensiveLaneIndependentlyMatched"] is False
    assert matched["release"]["data"]["g9CoverageSourceUrl"] is None

def test_g9_preference_cannot_pick_zone_without_goalie_g0_vulnerability():
    p=shooter(); g=goalie()
    matched=release_matched_to_g0_target(p,g,defense(["High Slot","L Circle"]))
    assert matched["release"]["data"]["zone"]=="L Circle"
    assert "High Slot" not in matched["release"]["data"]["consideredOwnGoalieWeakRoutes"]
