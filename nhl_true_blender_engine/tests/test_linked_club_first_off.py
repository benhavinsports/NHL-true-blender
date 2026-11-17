"""Real-source-shaped dated club report requires explicit goalie and game proof."""
import asyncio
from unittest.mock import patch

from nhl_true_blender_engine.club_morning_skate import (
    linked_same_day_club_reports,parse_first_off_club_article,collect_linked_club_reports)
from nhl_true_blender_engine.dfo_dated_starters import collect_dfo_goalies
from nhl_true_blender_engine.enrichment import attach,ingest
from nhl_true_blender_engine.engine import all_goalie_branches
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_dfo_dated_starters import (
    DATE,HTML,fixtures)

ARTICLE="https://lakingsinsider.com/2026/11/17/11-17-preview-game-day-bruins/"
DFO="https://www.dailyfaceoff.com/starting-goalies/"+DATE
LINKED=HTML.replace(
    '<div>Michael DiPietro</div>',
    f'<a href="{ARTICLE}">Zach Dooley</a><div>Michael DiPietro</div>')
REPORT="""<html><h1>11/17 Preview – Kings at Bruins</h1>
 <div>WHO: Los Angeles Kings (5-11-2) @ Boston Bruins (13-6-1)</div>
 <div>WHEN: Tuesday, November 17 at 4:00 PM Pacific</div>
 <p>KINGS VITALS: The Kings held a full-team morning skate today.</p>
 <p>Goaltender Darcy Kuemper was off the ice first this morning and it looks
 like he will start the trip opener for the Kings in Boston.</p>
 <p>BRUINS VITALS: Boston concludes a four-game homestand.</p>
 </html>"""

def test_discovers_only_provably_dated_club_article_from_source_link():
    assert linked_same_day_club_reports(LINKED,DATE)==[(ARTICLE,"LAK")]
    assert linked_same_day_club_reports(LINKED,"2026-11-18")==[]
    poison=LINKED.replace(ARTICLE,"https://untrusted-goalie.example/2026/11/17/matches")
    assert linked_same_day_club_reports(poison,DATE)==[]

def test_direct_sourced_first_off_is_expected_and_unique_not_a_favored_scorer():
    game=fixtures()[0]
    row=parse_first_off_club_article(REPORT,ARTICLE,DATE,game,"LAK")
    assert row is not None
    assert row["goalieId"]=="101"
    assert row["status"]=="EXPECTED"
    assert row["identityMatched"] is True
    assert row["datedEyewitnessMorningSkateFirstOff"] is True
    assert row["morningSkateSourceUrls"]==[ARTICLE]
    assert parse_first_off_club_article(REPORT,ARTICLE,"2026-11-18",game,"LAK") is None
    assert parse_first_off_club_article(REPORT.replace(
        "Los Angeles Kings (5-11-2) @ Boston Bruins",
        "Los Angeles Kings (5-11-2) @ Chicago Blackhawks"),ARTICLE,DATE,game,"LAK") is None
    assert parse_first_off_club_article(REPORT.replace(
        "Goaltender Darcy Kuemper was off the ice first",
        "Goaltender Darcy Kuemper was part of the goalie group"),
        ARTICLE,DATE,game,"LAK") is None
    assert parse_first_off_club_article(REPORT,ARTICLE,DATE,game,"BOS") is None

def test_competing_club_goalie_claims_are_never_accepted():
    game=fixtures()[0]
    both=REPORT.replace("BRUINS VITALS:",
        "Goaltender Anton Forsberg was off the ice first this morning. BRUINS VITALS:")
    assert parse_first_off_club_article(both,ARTICLE,DATE,game,"LAK") is None

def test_actual_source_page_follows_game_date_to_safely_resolve_projected_conflict(tmp_path):
    class Response:
        def __init__(self,text):self.text=text
        def raise_for_status(self):pass
    class Client:
        def __init__(self,*a,**kw):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def get(self,url):
            if url==DFO:return Response(LINKED)
            if url==ARTICLE:return Response(REPORT)
            raise AssertionError("Unexpected source URL "+url)
    games=fixtures()
    games[0]["date"]=DATE
    db=open_db(str(tmp_path/"club.sqlite"))
    try:
        ingest(db,{"evidence_id":"independent-algorithmic-forecast",
           "slate_date":DATE,"stage":"PROJECTED","game_id":games[0]["id"],
           "kind":"GOALIE_STARTER","source_url":
             "https://daily.hockey/starting-goalies/"+DATE,
           "observed_at":"2026-11-17T12:00:00Z",
           "payload":{"team":"LAK","goalieId":"102",
              "status":"EXPECTED","projectedPreferred":True}})
        with patch("nhl_true_blender_engine.dfo_dated_starters.httpx.AsyncClient",Client):
            result=asyncio.run(collect_dfo_goalies(db,{"games":games},DATE,"PROJECTED"))
        assert result["matchedStarterIds"]==3
        assert result["independentClubMorningSkate"]["matchedOfficialGoalieIds"]==1
        assert result["independentClubMorningSkate"]["matched"][0]["goalieId"]=="101"
        attach(db,{"games":games},DATE,"PROJECTED")
        assert {b["data"]["goalieId"] for b in games[0]["goalies"]["LAK"]}=={"101","102"}
        goalie=all_goalie_branches(games[0],"PROJECTED")["LAK"]
        assert len(goalie)==1
        assert goalie[0]["data"]["goalieId"]=="101"
        assert goalie[0]["data"]["status"]=="EXPECTED"
        assert ARTICLE in goalie[0]["data"]["morningSkateSourceUrls"]
    finally:
        db.close()
