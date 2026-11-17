"""Dated goalie source must unlock live G0 starter identities, never invent picks."""
from datetime import datetime
from unittest.mock import patch
import asyncio

from nhl_true_blender_engine.dated_goalie_projections import (
    parse_dated_projections,collect_dated_goalie_projections)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import attach

DATE="2026-11-17"
HTML="""<html><head><title>NHL starting goalies tonight</title></head>
<body><h1>NHL starting goalies tonight</h1><div>Tuesday, November 17, 2026</div>
<nav>LAK @ BOS EDM @ FLA</nav>
<article><h2>LAK @ BOS</h2><span>LAK · #31</span><a>Forsberg</a>
<span>69%</span><b>Leaning</b><span>VS</span>
<span>BOS · #30</span><a>DiPietro</a><span>82%</span><b>Likely</b>
<div>Other goalies</div><a>Darcy Kuemper</a></article>
<article><h2>EDM @ FLA</h2><span>EDM · #27</span><a>Levi</a>
<span>54%</span><b>Toss-up</b><span>VS</span>
<span>FLA · #25</span><a>Markstrom</a><span>92%</span><b>Likely</b>
</article></body></html>"""


def schedule():
    def goalie(id,name):
        return {"id":str(id),"name":name}
    return [
        {"id":"2026020333","away":"LAK","home":"BOS","goalies":{"LAK":[],"BOS":[]},
         "rosters":{
          "LAK":{"data":{"goalies":[goalie(100,"Anton Forsberg"),
                                     goalie(101,"Darcy Kuemper")]}},
          "BOS":{"data":{"goalies":[goalie(200,"Michael DiPietro"),
                                     goalie(201,"Jeremy Swayman")]}}}},
        {"id":"2026020335","away":"EDM","home":"FLA","goalies":{"EDM":[],"FLA":[]},
         "rosters":{
          "EDM":{"data":{"goalies":[goalie(300,"Devon Levi")]}},
          "FLA":{"data":{"goalies":[goalie(400,"Jacob Markstrom")]}}}}
    ]


def test_parse_only_exact_day_and_official_matchup_goalie_ids():
    rows,status=parse_dated_projections(HTML,DATE,schedule())
    assert status=="DATED_MATCHUPS_PARSED"
    assert len(rows)==4
    assert {(x["team"],x["goalieId"]) for x in rows}=={
        ("LAK","100"),("BOS","200"),("EDM","300"),("FLA","400")}
    assert next(x for x in rows if x["team"]=="LAK")["projectedPreferred"] is True
    assert next(x for x in rows if x["team"]=="EDM")["projectedPreferred"] is False


def test_yesterday_lineups_do_not_become_todays_projected_starters():
    rows,status=parse_dated_projections(HTML,"2026-11-18",schedule())
    assert rows==[]
    assert status=="SOURCE_SLATE_DATE_UNVERIFIED"


def test_unmatched_or_ambiguous_goalie_surname_is_never_a_starter():
    matches=schedule()
    matches[0]["rosters"]["LAK"]["data"]["goalies"].append({
        "id":"111","name":"Other Forsberg"})
    rows,status=parse_dated_projections(HTML,DATE,matches)
    assert status=="DATED_MATCHUPS_PARSED"
    assert len(rows)==2
    assert {x["team"] for x in rows}=={"EDM","FLA"}


def test_collect_source_labeled_expected_goalies_attaches_not_fake_confirmed(tmp_path):
    class Response:
        text=HTML
        def raise_for_status(self):
            pass
    class Client:
        def __init__(self,*args,**kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self,*args):
            pass
        async def get(self,url):
            assert url.endswith(DATE)
            return Response()
    snap={"games":schedule()}
    con=open_db(str(tmp_path/"dated.sqlite"))
    with patch("nhl_true_blender_engine.dated_goalie_projections.httpx.AsyncClient",Client):
        report=asyncio.run(collect_dated_goalie_projections(
            con,snap,DATE,"PROJECTED"))
    assert report["status"]=="DATED_MATCHUPS_PARSED"
    assert report["projectedGoalieReceipts"]==4
    assert report["gamesWithBothGoalieProjections"]==2
    rows=con.execute("SELECT kind,stage,payload FROM evidence").fetchall()
    assert len(rows)==4
    assert all(x["kind"]=="GOALIE_STARTER" and x["stage"]=="PROJECTED"
               for x in rows)
    attach(con,snap,DATE,"PROJECTED")
    assert len(snap["games"][0]["goalies"]["LAK"])==1
    assert snap["games"][0]["goalies"]["LAK"][0]["data"]["goalieId"]=="100"
    assert snap["games"][0]["goalies"]["LAK"][0]["data"]["status"]=="EXPECTED"
    assert snap["games"][1]["goalies"]["EDM"][0]["data"]["projectedPreferred"] is False
    assert all(x["data"]["status"]!="CONFIRMED"
        for game in snap["games"] for team in (game["away"],game["home"])
        for x in game["goalies"][team])
    con.close()


def test_unmatched_starting_goalie_is_categorized_as_identity_not_absent_source():
    games=schedule()
    games[0]["rosters"]["LAK"]["data"]["goalies"].append({
        "id":"111","name":"Another Forsberg"})
    trace=[]
    rows,status=parse_dated_projections(HTML,DATE,games,trace)
    assert status=="DATED_MATCHUPS_PARSED"
    assert len(rows)==2
    by_game={x["gameId"]:x["reason"] for x in trace}
    assert by_game["2026020333"]=="OFFICIAL_GOALIE_ID_UNMATCHED_OR_AMBIGUOUS"
    assert by_game["2026020335"]=="MATCHED"


def test_recoverable_source_failure_retries_but_keeps_expected_status(tmp_path):
    import httpx
    from nhl_true_blender_engine.dated_goalie_projections import ROOT
    calls=[]
    class Client:
        def __init__(self,*args,**kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self,*args):
            pass
        async def get(self,url):
            calls.append(url)
            response=httpx.Response(503 if len(calls)==1 else 200,
                                    request=httpx.Request("GET",url),
                                    text=HTML if len(calls)>1 else "retry")
            return response
    con=open_db(str(tmp_path/"retry.sqlite"))
    async def no_wait(*_):
        pass
    with patch("nhl_true_blender_engine.dated_goalie_projections.httpx.AsyncClient",Client), \
         patch("nhl_true_blender_engine.dated_goalie_projections.asyncio.sleep",no_wait):
        result=asyncio.run(collect_dated_goalie_projections(
            con,{"games":schedule()},DATE,"PROJECTED"))
    assert len(calls)==2
    assert result["boundedRetryCount"]==1
    assert result["status"]=="DATED_MATCHUPS_PARSED"
    assert result["matchupResearchReasons"]=={"MATCHED":2}
    assert result["projectedGoalieReceipts"]==4
    assert all(x["stage"]=="PROJECTED" for x in
               con.execute("SELECT stage FROM evidence"))
    con.close()
