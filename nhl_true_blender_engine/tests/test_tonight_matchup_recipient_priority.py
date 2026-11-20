"""G10.5: source-qualified THIS opponent outranks unrelated season goals.

The player shot-origin history still proves that the shooter owns a route.
It must not decide which *different* goalie/defense-matched route is more
attackable in tonight's game when the actual matchup evidence disagrees.
"""
from nhl_true_blender_engine.engine import challenger_proof
from nhl_true_blender_engine.tests.test_engine import skater


def _scene():
    candidate = skater(8501, "Low Slot", 8, 1)
    rival = skater(8502, "R Circle", 30, 7)
    goalies = {
        "Low Slot": {"leagueSavePctgPercentile": .08, "shotsAgainst": 58,
                     "goalsAgainst": 18, "sourceUrl": "https://nhl.com/goalie/slot"},
        "R Circle": {"leagueSavePctgPercentile": .66, "shotsAgainst": 48,
                     "goalsAgainst": 4, "sourceUrl": "https://nhl.com/goalie/circle"},
    }
    exposure = {
        "zoneConcessions": {
            "Low Slot": {"onNetShotsPerGame": 12, "peerMedianOnNetShotsPerGame": 8,
                         "independentOnNetConcessionReview": True,
                         "positiveConcessionBases": ["ON_NET_SHOTS_AGAINST_PEER"]},
            "R Circle": {"onNetShotsPerGame": 9, "peerMedianOnNetShotsPerGame": 8,
                         "independentOnNetConcessionReview": True,
                         "positiveConcessionBases": ["ON_NET_SHOTS_AGAINST_PEER"]},
        },
    }
    # Explicitly make both independently supported as goalie + defense areas.
    return candidate, rival, goalies, exposure


def test_tonight_aligned_route_beats_more_old_goals():
    candidate, rival, goalie, defense = _scene()
    winner, rows = challenger_proof(
        candidate, [rival], goalie, list(defense["zoneConcessions"]),
        opponent_coverage=defense)
    assert winner is True
    assert rows[0]["status"] == "DEFEATED"
    assert rows[0]["candidate"]["ownedGoals"] == 1
    assert rows[0]["challenger"]["ownedGoals"] == 7
    assert rows[0]["decisionBasis"] == "TONIGHT_OPPONENT_GOALIE_AND_DEFENSE"
    assert rows[0]["tonightMatchupComparison"]["result"] == "CANDIDATE"
    loser, rows = challenger_proof(
        rival, [candidate], goalie, list(defense["zoneConcessions"]),
        opponent_coverage=defense)
    assert loser is False and rows[0]["status"] == "RIVAL_DOMINATES"


def test_conflicting_goalie_and_defensive_advantages_never_force_a_winner():
    candidate, rival, goalie, defense = _scene()
    defense["zoneConcessions"]["R Circle"]["onNetShotsPerGame"] = 20
    ok, rows = challenger_proof(
        candidate, [rival], goalie, list(defense["zoneConcessions"]),
        opponent_coverage=defense)
    assert ok is False
    assert rows[0]["status"] == "NO_DECISIVE_ROUTE_SEPARATION"
    assert rows[0]["tonightMatchupComparison"]["result"] == "UNSEPARATED"


def test_missing_real_matchup_evidence_never_fabricated():
    candidate, rival, goalie, defense = _scene()
    defense["zoneConcessions"]["Low Slot"].pop("independentOnNetConcessionReview")
    _, rows = challenger_proof(
        candidate, [rival], goalie, list(defense["zoneConcessions"]),
        opponent_coverage=defense)
    assert rows[0]["tonightMatchupComparison"] is None
    assert rows[0]["decisionBasis"] == "HISTORICAL_OWN_FINISHING_FALLBACK_NOT_TONIGHT_PROOF"
