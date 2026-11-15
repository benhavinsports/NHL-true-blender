"""G0 first compares real goalies before evaluating any scorer."""
from nhl_true_blender_engine.engine import compare_g0_same_origin

def direction(attacker,goalie,shots,goals,percentile,zone="Low Slot"):
    return {"attacker":attacker,"targetGoalies":[{
        "goalieId":goalie,"status":"EXPECTED",
        "sourceUrl":f"https://api-web.nhle.com/v1/edge/goalie-shot-location-detail/{goalie}/now",
        "weakZones":{zone:{"shotsAgainst":shots,"goalsAgainst":goals,
            "leagueSavePctgPercentile":percentile}}}]}

def test_same_actual_low_slot_weakness_selects_only_measurably_more_vulnerable_goalie():
    # Real reported source metric pattern: one goalie 19 goals/56 shots,
    # opposite goalie 14/53. G0 should not be stuck comparing identical
    # strings {'Low Slot'} when empirical data separates goalies.
    attack_van=direction("VAN","8479394",53,14,.0702)
    attack_vgk=direction("VGK","8480947",56,19,.0175)
    assert compare_g0_same_origin(attack_van,attack_vgk) is attack_vgk
    assert compare_g0_same_origin(attack_vgk,attack_van) is attack_vgk

def test_inconsistent_peer_and_goal_rate_evidence_never_chooses_side():
    a=direction("VAN","1",53,14,.02)
    b=direction("VGK","2",56,19,.10)
    assert compare_g0_same_origin(a,b) is None

def test_mixed_or_missing_goalie_branches_do_not_collapse_to_single_guessed_starter():
    a=direction("VAN","1",53,14,.05)
    b=direction("VGK","2",56,19,.01)
    a["targetGoalies"].append(direction("VAN","3",40,10,.09)["targetGoalies"][0])
    assert compare_g0_same_origin(a,b) is None

def test_noncomparable_shot_areas_and_insufficient_samples_stay_unresolved():
    a=direction("VAN","1",53,14,.07)
    b=direction("VGK","2",56,19,.01,zone="R Circle")
    assert compare_g0_same_origin(a,b) is None
    b=direction("VGK","2",10,5,.01)
    assert compare_g0_same_origin(a,b) is None
