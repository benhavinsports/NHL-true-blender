"""Regression: preserve independently sourced G6 deployment fields and URLs."""
from unittest.mock import patch
from deployment_sources import parse_lineup_json, fetch_deployment


def test_full_club_name_and_typed_power_play_units_are_not_rejected():
    source={
        "players":[
            {"fullName":"Home Shooter","teamName":"New York Rangers",
             "lineNumber":2,"powerPlayUnit":1},
            {"fullName":"Home PP Two","teamName":"New York Rangers",
             "lineNumber":3,"ppUnit":"2"},
            {"fullName":"Opponent Shooter","teamName":"Boston Bruins",
             "lineNumber":1,"powerPlayUnit":1},
        ]
    }
    actual=parse_lineup_json(source,"NYR","official fixture")
    assert {row["playerName"] for row in actual}=={"Home Shooter","Home PP Two"}
    assert {row["playerName"]:row["powerPlayUnit"] for row in actual}=={
        "Home Shooter":1,"Home PP Two":2}
    assert {row["playerName"]:row["line"] for row in actual}=={
        "Home Shooter":2,"Home PP Two":3}


def test_explicit_pp_numeric_does_not_turn_generic_unit_into_pp():
    rows=parse_lineup_json({"players":[
        {"fullName":"Real PP","teamAbbrev":"CAR","ppUnit":2},
        {"fullName":"Generic Unit","teamAbbrev":"CAR","unit":2},
    ]},"CAR","fixture")
    assert len(rows)==1
    assert rows[0]["playerName"]=="Real PP"
    assert rows[0]["powerPlayUnit"]==2


def test_discovered_json_location_never_corrupts_source_url():
    url="https://www.nhl.com/news/verified-projected-lineup"
    discovered=[{"playerName":"Test Player","line":2,"powerPlayUnit":None,
                 "source":"General web search",
                 "sourcePath":url+" :: team.players[0]"}]
    with patch("deployment_sources.fetch_hockeyinsights",return_value=([],{})), \
         patch("deployment_sources.fetch_nhl_article",return_value=([],{})), \
         patch("deployment_sources.fetch_dailyfaceoff",return_value=([],{})), \
         patch("deployment_sources.fetch_web_search",
               return_value=(discovered,{"source":"General web search","url":url})):
        players,_=fetch_deployment("NYR","New York Rangers",slate_date="2026-11-21")
    assert players[0]["lineEvidence"][0]["sourceUrl"]==url
    # A web search URL must never manufacture the lineup's game-day date.
    assert players[0]["lineEvidence"][0]["sourceDate"] is None
