"""G10.5 same-lane comparisons use dated PBP shots per actual appearance."""
from nhl_true_blender_engine.engine import _same_lane_tonight_shot_opportunity
from nhl_true_blender_engine.tests.test_engine import skater, evidence, DATE, SRC


def _comparison(candidate_attempts=18, challenger_attempts=6):
    candidate = skater(85101, "slot", candidate_attempts, 2)
    challenger = skater(85102, "slot", challenger_attempts, 1)
    return candidate, challenger


def _set_recent_lane(player, counts, goals=None):
    ids=[f"sample-{player['id']}-{i+1}" for i in range(len(counts))]
    dates=[f"2026-11-{i+1:02d}" for i in range(len(counts))]
    goals=list(goals if goals is not None else [0]*len(counts))
    pressure_counts=list(counts)
    player["pressure"]["data"]={
        "recentAppearanceShots":pressure_counts,
        "appearances":[{"date":dates[i],"gameId":ids[i],
                        "shotsOnGoal":pressure_counts[i],"sourceUrl":SRC}
                       for i in range(len(counts))],
        "evidenceType":"OFFICIAL_HISTORICAL_SHOT_EVENTS",
        "scope":"SAMPLED_RECENT_TEAM_GAMES_ONLY"
    }
    zone=player["release"]["data"]["zone"]
    by_game=[{"gameId":ids[i],"date":dates[i],"shotsOnGoal":counts[i],
              "ownedGoals":goals[i],"sourceUrls":[SRC]}
             for i in range(len(counts))]
    player["recentOrigin"]=evidence({
        "sourceType":"OFFICIAL_NHL_DATED_PBP_SHOOTER_ORIGIN",
        "scope":"RECENT_PRE_SLATE_TARGET_CLUB_GAMES_ONLY",
        "sampleAsOfSlateDate":DATE,"sampleGameIds":ids,
        "sampleAppearanceCount":len(ids),
        "sampleSourcesByGame":{gid:[SRC] for gid in ids},
        "sampleCoverageComplete":True,
        "pbpBoxscoreSogReconciled":True,
        "pbpOnNetShotsByGame":{gid:counts[i] for i,gid in enumerate(ids)},
        "boxscoreShotsOnGoalByGame":{gid:counts[i] for i,gid in enumerate(ids)},
        "sampleIncludesActualZeroShotAppearances":True,
        "unclassifiedOnNetShots":0,
        "zoneCounts":{zone:{
            "shotsOnGoal":sum(counts),"ownedGoals":sum(goals),
            "gameIds":ids,"sourceUrls":[SRC],"byGame":by_game
        }},
        "rinkBinsApproximateNotNhlEdgePolygons":True,
        "historicalOwnGoalCreditOnly":True,
        "notTonightGoalPrediction":True
    },source=SRC+"/recent-origin")


def _run(candidate, challenger):
    return _same_lane_tonight_shot_opportunity(
        candidate, challenger,
        candidate["release"]["data"], challenger["release"]["data"],
        {"slot": {"shotsAgainst": 40, "goalsAgainst": 8}}, {"slot"},
    )


def test_dated_recent_same_lane_shot_pressure_can_be_compared():
    candidate, challenger = _comparison()
    _set_recent_lane(candidate,[5,4],[1,1])
    _set_recent_lane(challenger,[2,1],[0,0])
    proof = _run(candidate, challenger)
    assert proof is not None
    assert proof["result"] == "CANDIDATE"
    assert proof["bothHaveRecurringOwnShotPressure"] is True
    assert proof["sameLaneRecentShotComparison"]["comparison"] == (
        "RECENT_OFFICIAL_PBP_SAME_LANE_SHOTS_PER_ACTUAL_APPEARANCE")
    assert proof["seasonEdgeCumulativeShotsNotUsed"] is True


def test_undated_shot_counts_cannot_defeat_a_teammate():
    candidate, challenger = _comparison()
    _set_recent_lane(candidate,[5,4])
    _set_recent_lane(challenger,[2,1])
    challenger["pressure"]["data"].pop("appearances")
    assert _run(candidate, challenger) is None


def test_duplicate_appearance_dates_are_not_two_actual_games():
    candidate, challenger = _comparison()
    _set_recent_lane(candidate,[5,4])
    _set_recent_lane(challenger,[2,1])
    challenger["pressure"]["data"]["appearances"][1]["date"] = "2026-11-01"
    assert _run(candidate, challenger) is None


def test_unmatched_shot_count_and_date_lists_cannot_set_recipient():
    candidate, challenger = _comparison()
    _set_recent_lane(candidate,[5,4])
    _set_recent_lane(challenger,[2,1])
    candidate["pressure"]["data"]["recentAppearanceShots"].append(3)
    assert _run(candidate, challenger) is None


def test_recent_same_lane_rate_overrules_cumulative_season_volume():
    candidate, challenger = _comparison(40,12)
    _set_recent_lane(candidate,[1,1],[1,0])
    _set_recent_lane(challenger,[3,3],[0,0])
    proof=_run(candidate,challenger)
    assert proof["result"]=="RIVAL"
    assert proof["sameLaneRecentShotComparison"]["candidate"]["rateDenominator"]==2
    assert proof["sameLaneRecentShotComparison"]["rival"]["rateDenominator"]==2


def test_actual_appearance_rate_beats_raw_recent_shot_total():
    candidate, challenger = _comparison(40,12)
    _set_recent_lane(candidate,[1,1,1,1])
    _set_recent_lane(challenger,[2,1])
    proof=_run(candidate,challenger)
    assert proof["result"]=="RIVAL"


def test_missing_recent_pbp_or_equal_rates_remain_unresolved():
    candidate, challenger = _comparison()
    _set_recent_lane(candidate,[2,2],[2,0])
    _set_recent_lane(challenger,[2,2],[0,0])
    challenger.pop("recentOrigin")
    assert _run(candidate,challenger) is None
    _set_recent_lane(challenger,[2,2],[0,0])
    proof=_run(candidate,challenger)
    assert proof["result"]=="UNSEPARATED"
