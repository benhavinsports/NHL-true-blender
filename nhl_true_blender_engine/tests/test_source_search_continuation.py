"""Regression: incomplete sources trigger research, never automatic G0-G18 passes."""
from datetime import datetime, timezone
from unittest.mock import patch

from deployment_sources import fetch_deployment
from nhl_true_blender_engine.engine import MASTER
from nhl_true_blender_engine.source_recovery import recovery_snapshot

DATE = "2026-11-21"
NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


class GateRows:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, parameters):
        assert parameters == (DATE, "PROJECTED")
        return self.rows


def game(gid="7", start="2026-11-21T23:00:00Z"):
    return {"id": gid, "gameState": "FUT", "startUTC": start}


def gate(gid, player, name, status):
    return {"game_id": gid, "player_id": player,
            "gate": name, "disposition": status}


def recover(rows, games=None, selected=None):
    return recovery_snapshot(
        GateRows(rows), {"games": games if games is not None else [game()]},
        DATE, "PROJECTED",
        {"g0TwoGoalieDirectionDecisions": selected if selected is not None
         else {"7": {"attacker": "NYI"}}}, now=NOW)


def test_later_unresolved_gates_after_earlier_elimination_still_trigger_research():
    # G2 is a genuine, permanent elimination. It must not suppress independent
    # source recovery for later G6 and G11 rows that remain NOT_EXECUTED.
    rows = [gate("7", "42", name,
                 "ELIMINATED" if name == "G2" else
                 "NOT_EXECUTED" if name in ("G6", "G11") else "PASS")
            for name in MASTER[:-1]]
    assert [x["id"] for x in recover(rows)["games"]] == ["7"]


def test_missing_later_gate_after_earlier_elimination_still_triggers_research():
    # Missing a downstream gate row is incomplete execution, not proof that
    # the gate was considered. Recovery must revisit the still-pregame game.
    rows = [gate("7", "42", name,
                 "ELIMINATED" if name == "G2" else "PASS")
            for name in MASTER[:-1] if name != "G7"]
    assert [x["id"] for x in recover(rows)["games"]] == ["7"]


def test_genuine_elimination_is_not_reopened_when_all_evidence_is_accounted_for():
    # A complete, source-accounted elimination does not reopen the player.
    rows = [gate("7", "42", name, "ELIMINATED" if name == "G2" else "PASS")
            for name in MASTER[:-1]]
    assert recover(rows)["games"] == []


def test_unresolved_g0_and_zero_skater_matrices_still_trigger_research():
    assert [x["id"] for x in recover([])["games"]] == ["7"]
    assert [x["id"] for x in recover([], selected={})["games"]] == ["7"]


def test_started_games_are_never_reopened_for_new_source_selection():
    assert recover([], games=[game(start="2026-11-21T11:59:00Z")])["games"] == []


def test_only_unselected_g18_is_not_a_reason_to_research_source_gates():
    rows = [gate("7", "42", name, "PASS") for name in MASTER[:-1]]
    rows.append(gate("7", "42", "G18", "NOT_EXECUTED"))
    assert recover(rows)["games"] == []


def _source(rows, dated=True):
    return rows, {
        "source": "Hockey Insights snapshot",
        "url": "https://hockeyinsights.ca/data/lineups/ANA.json",
        "sourceDate": DATE if dated else "2026-11-20",
        "dateVerified": True if dated else False,
    }


def _no_source(*args, **kwargs):
    return [], {"source": None, "errors": ["No parsed assignments"]}


def test_partial_different_player_line_and_pp_cannot_end_web_discovery():
    rows = [{"playerName": "Skater One", "line": 1},
            {"playerName": "Skater Two", "powerPlayUnit": 2}]
    with patch("deployment_sources.fetch_hockeyinsights", return_value=_source(rows)), \
         patch("deployment_sources.fetch_nhl_article", side_effect=_no_source), \
         patch("deployment_sources.fetch_dailyfaceoff", side_effect=_no_source), \
         patch("deployment_sources.fetch_web_search", side_effect=_no_source) as search:
        _, audit = fetch_deployment(
            "ANA", "anaheim-ducks", slate_date=DATE,
            expected_player_names=["Skater One", "Skater Two", "Skater Three"])
    search.assert_called_once()
    assert audit["researchContinuationRequired"] is True
    assert audit["sourceSearchComplete"] is False
    assert audit["remainingOfficialRosterIdentityCount"] == 1


def test_stale_full_lineup_does_not_stop_search_for_dated_source():
    rows = [{"playerName": "Skater One", "line": 1, "powerPlayUnit": 1}]
    with patch("deployment_sources.fetch_hockeyinsights",
               return_value=_source(rows, dated=False)), \
         patch("deployment_sources.fetch_nhl_article", side_effect=_no_source), \
         patch("deployment_sources.fetch_dailyfaceoff", side_effect=_no_source), \
         patch("deployment_sources.fetch_web_search", side_effect=_no_source) as search:
        _, audit = fetch_deployment(
            "ANA", "anaheim-ducks", slate_date=DATE,
            expected_player_names=["Skater One"])
    search.assert_called_once()
    assert audit["researchContinuationRequired"] is True


def test_complete_dated_known_player_evidence_needs_no_duplicate_search():
    rows = [{"playerName": "Skater One", "line": 1, "powerPlayUnit": 1}]
    with patch("deployment_sources.fetch_hockeyinsights", return_value=_source(rows)), \
         patch("deployment_sources.fetch_nhl_article", side_effect=_no_source), \
         patch("deployment_sources.fetch_dailyfaceoff", side_effect=_no_source), \
         patch("deployment_sources.fetch_web_search", side_effect=_no_source) as search:
        _, audit = fetch_deployment(
            "ANA", "anaheim-ducks", slate_date=DATE,
            expected_player_names=["Skater One"])
    search.assert_not_called()
    assert audit["sourceSearchComplete"] is True
