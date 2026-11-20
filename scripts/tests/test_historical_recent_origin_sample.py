from scripts.reconstruct_historical_pbp import build_player_recent_origin_sample

URL1="https://api-web.nhle.com/v1/gamecenter/2026020001/play-by-play"
URL2="https://api-web.nhle.com/v1/gamecenter/2026020002/play-by-play"


def test_recent_origin_sample_keeps_actual_zero_shot_appearances_in_denominator():
    appearances=[
        {"gameId":"2026020001","date":"2026-11-01","shotsOnGoal":2},
        {"gameId":"2026020002","date":"2026-11-02","shotsOnGoal":0},
    ]
    cached={
        "2026020001":[
            {"gameId":"2026020001","eventId":"1","shooterId":"700","type":"goal",
             "date":"2026-11-01","x":60,"y":3,"sourceUrl":URL1},
            {"gameId":"2026020001","eventId":"2","shooterId":"700","type":"shot-on-goal",
             "date":"2026-11-01","x":60,"y":3,"sourceUrl":URL1},
        ],
        "2026020002":[
            {"gameId":"2026020002","eventId":"3","shooterId":"701","type":"shot-on-goal",
             "date":"2026-11-02","x":50,"y":10,"sourceUrl":URL2},
        ],
    }
    payload,urls=build_player_recent_origin_sample(
        "700",appearances,cached,"2026-11-03","BOS")
    assert payload["sampleCoverageComplete"] is True
    assert payload["sampleGameIds"]==["2026020001","2026020002"]
    assert payload["sampleAppearanceCount"]==2
    assert payload["sampleSourcesByGame"]=={
        "2026020001":[URL1],"2026020002":[URL2]}
    assert payload["zoneCounts"]["High Slot"]["shotsOnGoal"]==2
    assert payload["zoneCounts"]["High Slot"]["ownedGoals"]==1
    assert payload["zoneCounts"]["High Slot"]["byGame"]==[{
        "gameId":"2026020001","date":"2026-11-01","shotsOnGoal":2,
        "ownedGoals":1,"sourceUrls":[URL1]}]
    assert urls==[URL1,URL2]


def test_unmapped_on_net_shot_prevents_source_verified_zero_lane():
    appearances=[
        {"gameId":"2026020001","date":"2026-11-01","shotsOnGoal":1},
        {"gameId":"2026020002","date":"2026-11-02","shotsOnGoal":1},
    ]
    cached={
        "2026020001":[
            {"gameId":"2026020001","eventId":"1","shooterId":"700","type":"shot-on-goal",
             "date":"2026-11-01","x":60,"y":3,"sourceUrl":URL1},
        ],
        "2026020002":[
            {"gameId":"2026020002","eventId":"2","shooterId":"700","type":"shot-on-goal",
             "date":"2026-11-02","x":None,"y":None,"sourceUrl":URL2},
        ],
    }
    payload,urls=build_player_recent_origin_sample(
        "700",appearances,cached,"2026-11-03","BOS")
    assert urls==[URL1,URL2]
    assert payload["unclassifiedOnNetShots"]==1
    assert payload["sampleCoverageComplete"] is False


def test_missing_pbp_game_does_not_become_a_measured_zero_appearance():
    appearances=[
        {"gameId":"2026020001","date":"2026-11-01","shotsOnGoal":1},
        {"gameId":"2026020002","date":"2026-11-02","shotsOnGoal":0},
    ]
    cached={
        "2026020001":[
            {"gameId":"2026020001","eventId":"1","shooterId":"700","type":"shot-on-goal",
             "date":"2026-11-01","x":60,"y":3,"sourceUrl":URL1},
        ],
    }
    payload,urls=build_player_recent_origin_sample(
        "700",appearances,cached,"2026-11-03","BOS")
    assert urls==[URL1]
    assert payload["sampleCoverageComplete"] is False
    assert payload["sampleGameIds"]==["2026020001","2026020002"]
