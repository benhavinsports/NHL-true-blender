"""G0/G9 route selection is tonight-opponent first, not career-lane first."""
from nhl_true_blender_engine.engine import release_matched_to_g0_target
from nhl_true_blender_engine.tests.test_engine import skater, evidence


def _sample():
    p=skater(9091,"R Circle",40,8)
    p["release"]["data"]["allRoutes"]=[
        {"zone":"R Circle","sog":40,"ownedGoals":8},
        {"zone":"Low Slot","sog":10,"ownedGoals":1},
    ]
    goalie=evidence({"weakZones":{
        "Low Slot":{"leagueSavePctgPercentile":.05,
                    "shotsAgainst":60,"goalsAgainst":14,
                    "sourceUrl":"https://nhl.com/goalie-slot"},
        "R Circle":{"leagueSavePctgPercentile":.70,
                    "shotsAgainst":50,"goalsAgainst":4,
                    "sourceUrl":"https://nhl.com/goalie-circle"},
    }})
    cover=evidence({"greenWeakZones":["Low Slot","R Circle"],
        "zoneConcessions":{
            "Low Slot":{"onNetShotsPerGame":14,
                "peerMedianOnNetShotsPerGame":8,
                "independentOnNetConcessionReview":True,
                "positiveConcessionBases":["ON_NET_SHOTS_AGAINST_PEER"]},
            "R Circle":{"onNetShotsPerGame":9,
                "peerMedianOnNetShotsPerGame":8,
                "independentOnNetConcessionReview":True,
                "positiveConcessionBases":["ON_NET_SHOTS_AGAINST_PEER"]},
        }})
    return p,goalie,cover


def test_tonight_opponent_weak_lane_selected_even_with_fewer_old_goals():
    p,goalie,cover=_sample()
    result=release_matched_to_g0_target(p,goalie,cover)
    r=result["release"]["data"]
    assert r["zone"]=="Low Slot"
    assert r["ownedGoals"]==1
    assert r["originalPrimaryOrigin"]=="R Circle"
    assert r["g9DefensiveLaneIndependentlyMatched"] is True
    assert r["tonightRouteSelectionBasis"]=="G0_GOALIE_G9_DEFENSE_MATCHUP_DOMINANCE"
    assert p["release"]["data"]["zone"]=="R Circle"


def test_conflicting_matchup_indicators_not_called_clear_tonight_alignment():
    p,goalie,cover=_sample()
    cover["data"]["zoneConcessions"]["R Circle"]["onNetShotsPerGame"]=20
    r=release_matched_to_g0_target(p,goalie,cover)["release"]["data"]
    assert r["tonightRouteSelectionBasis"]=="UNRESOLVED_MATCHUP_NO_HISTORICAL_FALLBACK"
    assert r["tonightRouteUnresolved"] is True
    assert r["zone"]=="R Circle"
