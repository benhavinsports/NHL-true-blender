"""G9 must not select or veto a route before the earlier G5 decision."""
from inspect import signature

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
                                "L Circle":{"shotsAgainst":42}}},
                  S+"/edge/goalie-shot-location-detail/88/now")


def test_g0_preserves_every_matching_route_without_using_g9():
    p=shooter()
    matched=release_matched_to_g0_target(p,goalie())
    data=matched["release"]["data"]
    assert data["zone"] is None
    assert data["g0MatchedOwnOriginRouteZones"]==["L Circle","Low Slot"]
    assert data["g9RouteSelectionDeferred"] is True
    assert data["g0RouteSelectionBasis"]=="G0_ONLY_GOALIE_WEAKNESS_ROUTE_SET"
    assert "g9ViableRoutes" not in data
    assert "g9DefensiveLaneIndependentlyMatched" not in data
    assert p["release"]["data"]["zone"]=="Low Slot"


def test_g9_coverage_is_not_an_input_to_g0_route_resolution():
    assert len(signature(release_matched_to_g0_target).parameters)==2


def test_green_or_red_g9_coverage_cannot_change_the_g0_matched_route_set():
    p=shooter()
    matched=release_matched_to_g0_target(p,goalie())
    zones=matched["release"]["data"]["g0MatchedOwnOriginRouteZones"]
    assert zones==["L Circle","Low Slot"]
    assert "High Slot" not in zones
