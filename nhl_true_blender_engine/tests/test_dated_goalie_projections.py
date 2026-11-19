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
    assert len(rows)==3
    assert {x["team"] for x in rows}=={"BOS","EDM","FLA"}
    assert not any(x["team"]=="LAK" for x in rows)


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
    assert len(rows)==3
    by_game={x["gameId"]:x for x in trace}
    assert by_game["2026020333"]["reason"]=="PARTIAL_OFFICIAL_GOALIE_ID_MATCH"
    assert by_game["2026020333"]["matchedTeamCount"]==1
    assert by_game["2026020333"]["teamResearch"]["LAK"]["reason"]=="OFFICIAL_GOALIE_ID_UNMATCHED_OR_AMBIGUOUS"
    assert by_game["2026020333"]["teamResearch"]["BOS"]["reason"]=="MATCHED"
    assert by_game["2026020335"]["reason"]=="MATCHED"


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


def test_partial_match_retains_only_verified_goalie_without_inventing_g0_branch(tmp_path):
    games=schedule()
    games[0]["rosters"]["LAK"]["data"]["goalies"].append({
        "id":"111","name":"Other Forsberg"})
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
            return Response()
    con=open_db(str(tmp_path/"partial.sqlite"))
    try:
        snap={"games":games}
        with patch("nhl_true_blender_engine.dated_goalie_projections.httpx.AsyncClient",Client):
            report=asyncio.run(collect_dated_goalie_projections(
                con,snap,DATE,"PROJECTED"))
        assert report["projectedGoalieReceipts"]==3
        assert report["gamesWithBothGoalieProjections"]==1
        assert report["gamesWithOnlyOneMatchedGoalie"]==1
        assert report["partialMatchesDoNotEstablishBothG0Directions"] is True
        assert report["matchupResearchReasons"]=={
            "MATCHED":1,"PARTIAL_OFFICIAL_GOALIE_ID_MATCH":1}
        attach(con,snap,DATE,"PROJECTED")
        # Other team's independent identity survives as EXPECTED; it does
        # not substitute for an unmatched goalie nor confirm either team.
        assert not snap["games"][0]["goalies"]["LAK"]
        assert len(snap["games"][0]["goalies"]["BOS"])==1
        assert snap["games"][0]["goalies"]["BOS"][0]["data"]["goalieId"]=="200"
        assert snap["games"][0]["goalies"]["BOS"][0]["data"]["status"]=="EXPECTED"
        assert len(con.execute("SELECT * FROM evidence WHERE kind='GOALIE_STARTER'").fetchall())==3
    finally:
        con.close()


def test_source_card_with_unparsed_opponent_retains_only_exact_verified_side():
    games=schedule()[:1]
    incomplete=HTML.replace(
        "<span>BOS · #30</span><a>DiPietro</a><span>82%</span><b>Likely</b>",
        "<span>BOS starter awaiting publication</span>")
    trace=[]
    rows,status=parse_dated_projections(incomplete,DATE,games,trace)
    assert status=="DATED_MATCHUPS_PARSED"
    assert [(row["team"],row["goalieId"]) for row in rows]==[("LAK","100")]
    assert trace[0]["matchedTeamCount"]==1
    assert trace[0]["teamResearch"]["BOS"]["reason"]=="STARTER_FIELDS_NOT_PARSED"


def test_live_display_repeated_surname_and_fullname_resolves_exact_official_ids():
    # The real page includes text from both its surname link and accessible
    # full-name label. Flattening the DOM yields "Forsberg Anton Forsberg",
    # NOT an unknown goalie or two separate players.
    from nhl_true_blender_engine.dated_goalie_projections import _lookup_goalie
    duplicated=(HTML
        .replace("<a>Forsberg</a>", "<a>Forsberg</a><span>Anton Forsberg</span>")
        .replace("<a>DiPietro</a>", "<a>DiPietro</a><span>Michael DiPietro</span>")
        .replace("<a>Levi</a>", "<a>Levi</a><span>Devon Levi</span>")
        .replace("<a>Markstrom</a>", "<a>Markstrom</a><span>Jacob Markstrom</span>"))
    trace=[]
    rows,status=parse_dated_projections(duplicated,DATE,schedule(),trace)
    assert status=="DATED_MATCHUPS_PARSED"
    assert {(r["team"],r["goalieId"]) for r in rows}=={
        ("LAK","100"),("BOS","200"),("EDM","300"),("FLA","400")}
    assert len(rows)==4 and all(r["sourceDisplayNameRepeated"] for r in rows)
    assert [x["reason"] for x in trace]==["MATCHED","MATCHED"]
    assert all(x["matchedTeamCount"]==2 for x in trace)
    assert trace[0]["teamResearch"]["LAK"]["sourceGoalieName"]=="Forsberg Anton Forsberg"
    # The repeated name provides an EXACT full official identity, but an
    # isolated surname with two possible officials stays ambiguous.
    rivals=[{"id":"100","name":"Anton Forsberg"},
            {"id":"101","name":"Other Forsberg"}]
    assert _lookup_goalie("Forsberg",rivals) is None
    assert _lookup_goalie("Forsberg Anton Forsberg",rivals)["id"]=="100"
    assert _lookup_goalie("Forsberg Anton Somebody",rivals) is None
    # Two identically named roster entries are never guessed.
    duplicate_ids=[{"id":"100","name":"Anton Forsberg"},
                   {"id":"101","name":"Anton Forsberg"}]
    assert _lookup_goalie("Forsberg Anton Forsberg",duplicate_ids) is None


def test_repeated_display_name_is_retained_in_expected_goalie_evidence(tmp_path):
    from json import loads
    class Response:
        text=HTML.replace("<a>Forsberg</a>",
            "<a>Forsberg</a><span>Anton Forsberg</span>")
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
            return Response()
    con=open_db(str(tmp_path/"display.sqlite"))
    try:
        with patch("nhl_true_blender_engine.dated_goalie_projections.httpx.AsyncClient",Client):
            report=asyncio.run(collect_dated_goalie_projections(
                con,{"games":schedule()},DATE,"PROJECTED"))
        assert report["projectedGoalieReceipts"]==4
        assert report["gamesWithBothGoalieProjections"]==2
        source=con.execute("SELECT payload FROM evidence WHERE kind='GOALIE_STARTER'").fetchall()
        payloads=[loads(row["payload"]) for row in source]
        expected=next(x for x in payloads if x["goalieId"]=="100")
        assert expected["originalSourceDisplayName"]=="Forsberg Anton Forsberg"
        assert expected["sourceDisplayNameRepeated"] is True
        assert expected["status"]=="EXPECTED"
        assert expected["notTeamConfirmed"] is True
        assert all(x["status"]!="CONFIRMED" for x in payloads)
    finally:
        con.close()


def test_later_more_complete_fixture_card_replaces_early_partial_card():
    first=HTML.replace(
        "<span>BOS · #30</span><a>DiPietro</a><span>82%</span><b>Likely</b>",
        "<span>BOS starter pending</span>")
    extra=("<article><h2>LAK @ BOS</h2>"
           "<span>LAK · #31</span><a>Forsberg</a><span>69%</span><b>Leaning</b>"
           "<span>BOS · #30</span><a>DiPietro</a><span>82%</span><b>Likely</b>"
           "</article>")
    full=first.replace("</body>", extra+"</body>")
    trace=[]
    rows,status=parse_dated_projections(full,DATE,schedule(),trace)
    assert status=="DATED_MATCHUPS_PARSED"
    assert len(rows)==4
    assert trace[0]["reason"]=="MATCHED"
    assert trace[0]["matchedTeamCount"]==2
    assert {(v["team"],v["goalieId"]) for v in rows}=={
        ("LAK","100"),("BOS","200"),("EDM","300"),("FLA","400")}


def test_conflicting_exact_goalie_ids_across_cards_remain_unresolved():
    extra=("<article><h2>LAK @ BOS</h2>"
           "<span>LAK · #35</span><a>Kuemper</a><span>91%</span><b>Likely</b>"
           "<span>BOS · #30</span><a>DiPietro</a><span>82%</span><b>Likely</b>"
           "</article>")
    duplicated=HTML.replace("</body>",extra+"</body>")
    trace=[]
    rows,status=parse_dated_projections(duplicated,DATE,schedule(),trace)
    assert status=="DATED_MATCHUPS_PARSED"
    assert not any(r["team"]=="LAK" for r in rows)
    assert {(r["team"],r["goalieId"]) for r in rows}=={
        ("BOS","200"),("EDM","300"),("FLA","400")}
    assert trace[0]["reason"]=="PARTIAL_OFFICIAL_GOALIE_ID_MATCH"
    assert trace[0]["teamResearch"]["LAK"]["reason"]=="CONFLICTING_SOURCE_STARTER_IDENTITIES"
    assert trace[0]["teamResearch"]["LAK"]["noArbitraryStarterSelection"] is True
