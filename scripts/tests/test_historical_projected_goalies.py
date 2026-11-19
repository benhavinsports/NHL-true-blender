"""Historical G0 independent projected goalie identity: source date and team scope."""
from scripts.ingest_nhl_historical_previews import (
    Article, first_listed_projected_goalie, goalie_id_index)


def test_earliest_named_official_projected_goalie_only_status_expected():
    roster = {"goalies": [
        {"id": 101, "firstName": {"default": "Jeremy"}, "lastName": {"default": "Swayman"}},
        {"id": 102, "firstName": {"default": "Joonas"}, "lastName": {"default": "Korpisalo"}}]}
    goalie_ids = goalie_id_index(roster)
    article = Article()
    article.feed("""
        <h2>Bruins projected lineup</h2>
        <p>Player One -- Player Two -- Player Three</p>
        <p>Player Four -- Player Five -- Player Six</p>
        <p>Player Seven -- Player Eight -- Player Nine</p>
        <p>Player Ten -- Player Eleven -- Player Twelve</p>
        <p>Player Thirteen -- Player Fourteen</p>
        <p>Player Fifteen -- Player Sixteen</p>
        <p>Player Seventeen -- Player Eighteen</p>
        <p>Jeremy Swayman</p>
        <p>Joonas Korpisalo</p>
        <p>Scratched: Other Player</p>
        <h2>Rangers projected lineup</h2>
        <p>Other Goalie</p>
    """)
    article._flush()
    result = first_listed_projected_goalie(article.lines, "BOS", goalie_ids)
    assert result["goalie"]["id"] == "101"
    assert [x["id"] for x in result["publishedGoalies"]] == ["101", "102"]
    assert result["sourceDoesNotConfirmStarter"] is True
    assert first_listed_projected_goalie(article.lines, "NYR", goalie_ids) is None


def test_no_guess_when_no_explicit_goalie_name_in_source_section():
    article = Article()
    article.feed("""
        <h2>Bruins projected lineup</h2>
        <p>Player One -- Player Two -- Player Three</p>
        <p>Player Four -- Player Five</p>
        <p>Status report</p>
        <p>Jeremy Swayman will be evaluated tomorrow</p>
    """)
    article._flush()
    goalie_ids = {"jeremyswayman": {"id": "101", "name": "Jeremy Swayman"}}
    assert first_listed_projected_goalie(article.lines, "BOS", goalie_ids) is None


def test_never_arbitrarily_picks_duplicate_goalie_identifiers():
    roster = {"goalies": [
        {"id": 101, "firstName": {"default": "J"}, "lastName": {"default": "Smith"}},
        {"id": 102, "firstName": {"default": "J"}, "lastName": {"default": "Smith"}}]}
    assert "jsmith" not in goalie_id_index(roster)
