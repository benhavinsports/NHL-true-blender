from scripts.replay_postgame_research import _approx_zones, _baseline


def test_postgame_rink_coordinates_use_engine_approximate_zone_mapping():
    assert "Low Slot" in _approx_zones({"x": 80, "y": 5})
    assert "High Slot" in _approx_zones({"x": 60, "y": 5})
    assert "L Circle" in _approx_zones({"x": 65, "y": 20})
    assert _approx_zones({"x": None, "y": None}) == []


def test_same_pool_baseline_uses_highest_pregame_shots_one_per_game():
    pool = [
        {"gameId": "1", "playerId": "a", "ownShotsOnGoal": 8},
        {"gameId": "1", "playerId": "b", "ownShotsOnGoal": 12},
        {"gameId": "2", "playerId": "c", "ownShotsOnGoal": 9},
        {"gameId": "3", "playerId": "d", "ownShotsOnGoal": 4},
    ]
    picks = _baseline(pool, 3)
    assert [(x["gameId"], x["playerId"]) for x in picks] == [
        ("1", "b"), ("2", "c"), ("3", "d")
    ]
