"""Regression checks for retrospective official-NHL research boundaries."""
from datetime import datetime, timezone
from scripts.reconstruct_historical_pbp import (
    event_available_before, league_pregame_games, _player_route, utc)


def _game(id, start, state="OFF"):
    return {"id": str(id), "startTimeUTC": start, "gameState": state}


def test_only_finished_games_with_six_hour_buffer():
    cutoff = utc("2026-10-02T02:00:00Z")
    assert not event_available_before(_game(1, "2026-10-01T20:00:00Z"), cutoff)
    assert event_available_before(_game(1, "2026-10-01T19:59:59Z"), cutoff)
    assert not event_available_before(_game(2, "2026-10-01T01:00:00Z", "FUT"), cutoff)


def test_future_game_and_post_cutoff_period_never_enter_peer_cohort():
    cutoff = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)
    old = _game(1, "2026-09-28T23:00:00Z")
    same_day_late = _game(2, "2026-10-02T23:00:00Z")
    not_complete = _game(3, "2026-09-28T23:00:00Z", "LIVE")
    population = league_pregame_games(
        {"A": [old, same_day_late],
         "B": [old, not_complete]}, cutoff)
    assert set(population) == {"1"}


def test_own_shot_origin_tie_stays_unresolved():
    def area():
        return {"shotsOnGoal": 5, "ownedGoals": 1,
                "sourceUrls": ["https://api-web.nhle.com/v1/gamecenter/1/play-by-play"]}
    assert _player_route({"Low Slot": area(), "High Slot": area()}) is None


def test_own_origin_never_claims_goal_mouth():
    sample = {"Low Slot": {"shotsOnGoal": 7, "ownedGoals": 2,
                          "sourceUrls": ["https://api-web.nhle.com/v1/gamecenter/1/play-by-play"]}}
    observed = _player_route(sample)
    assert observed["zone"] == "Low Slot"
    assert observed["isAnatomicalReleaseClaim"] is False
    assert observed["sourceType"] == "OFFICIAL_PRE_SLATE_PBP_SHOT_ORIGIN"
