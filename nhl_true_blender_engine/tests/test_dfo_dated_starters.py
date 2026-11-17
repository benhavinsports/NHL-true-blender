"""Dated live goalie reports are evidence, never a scorer shortcut."""
import asyncio
from unittest.mock import patch

from nhl_true_blender_engine.dfo_dated_starters import (
    parse_dfo_starters,collect_dfo_goalies)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import attach

DATE="2026-11-17"
HTML="""<html><head><title>NHL Starting Goalies - November 17, 2026</title></head>
<body><h1>NHL Starting Goalies: Tuesday, November 17</h1>
<div>Los Angeles Kings at Boston Bruins</div><div>2026-11-18T00:00:00.000Z</div>
<div>Darcy Kuemper</div><span>Likely</span><p>2026-11-17T16:30:00.000Z</p>
<div>Michael DiPietro</div><span>Confirmed</span><p>2026-11-17T16:18:46.777Z</p>
<div>Toronto Maple Leafs at Chicago Blackhawks</div><div>2026-11-18T00:30:00.000Z</div>
<div>Sergei Bobrovsky</div><span>Confirmed</span><p>2026-11-17T17:14:10.242Z</p>
<div>Spencer Knight</div><span>Unconfirmed</span>
</body></html>"""

def fixtures():
    goalie=lambda pid,name:{"id":str(pid),"name":name}
    return [
      {"id":"2026020333","away":"LAK","home":"BOS",
       "startUTC":"2026-11-18T00:00:00Z",
       "goalies":{"LAK":[],"BOS":[]},
       "rosters":{
        "LAK":{"data":{"goalies":[goalie(101,"Darcy Kuemper"),goalie(102,"Anton Forsberg")]}},
        "BOS":{"data":{"goalies":[goalie(201,"Michael DiPietro"),goalie(202,"Jeremy Swayman")]}}}},
      {"id":"2026020338","away":"TOR","home":"CHI",
       "startUTC":"2026-11-18T00:30:00Z",
       "goalies":{"TOR":[],"CHI":[]},
       "rosters":{
        "TOR":{"data":{"goalies":[goalie(301,"Sergei Bobrovsky"),goalie(302,"Anthony Stolarz")]}},
        "CHI":{"data":{"goalies":[goalie(401,"Spencer Knight"),goalie(402,"Arvid Soderblom")]}}}}
    ]


def test_exact_date_two_matching_official_ids_and_statuses():
    diagnostics=[]
    rows,status=parse_dfo_starters(HTML,DATE,fixtures(),diagnostics)
    assert status=="MATCHED_DATED_STARTERS"
    assert {(x["team"],x["goalieId"],x["status"]) for x in rows}=={
       ("LAK","101","EXPECTED"),("BOS","201","CONFIRMED"),("TOR","301","CONFIRMED")}
    assert not any(x["team"]=="CHI" for x in rows)
    assert any(d.get("reason")=="SOURCE_STARTER_UNCONFIRMED_NO_PREFERRED_ID"
               for d in diagnostics)
    assert next(x for x in rows if x["team"]=="LAK")["projectedPreferred"] is True
    assert next(x for x in rows if x["team"]=="BOS")["projectedPreferred"] is False


def test_wrong_date_game_start_or_narrative_goalie_name_do_not_unlock_a_starter():
    rows,status=parse_dfo_starters(HTML,"2026-11-18",fixtures())
    assert rows==[] and status=="SOURCE_DATE_UNVERIFIED"
    bad=HTML.replace("2026-11-18T00:00:00.000Z","2026-11-19T00:00:00.000Z")
    rows,_=parse_dfo_starters(bad,DATE,fixtures())
    assert {x["team"] for x in rows}=={"TOR"}
    bad=HTML.replace("<div>Darcy Kuemper</div><span>Likely</span>",
      "<div>Darcy Kuemper is likely after warmups</div>")
    rows,_=parse_dfo_starters(bad,DATE,fixtures())
    assert not any(x["team"]=="LAK" for x in rows)


def test_unmatched_goalie_and_ambiguous_roster_ids_are_not_picked():
    games=fixtures()
    games[0]["rosters"]["BOS"]["data"]["goalies"]=[
      {"id":"1","name":"Wrong Goalie"}]
    rows,_=parse_dfo_starters(HTML,DATE,games)
    assert not any(x["team"]=="BOS" for x in rows)
    games=fixtures()
    games[0]["rosters"]["BOS"]["data"]["goalies"].append(
      {"id":"999","name":"Michael DiPietro"})
    rows,_=parse_dfo_starters(HTML,DATE,games)
    assert not any(x["team"]=="BOS" for x in rows)


def test_collector_ingests_source_status_without_promoting_likely_to_confirmed(tmp_path):
    class Reply:
        text=HTML
        def raise_for_status(self): pass
    class Client:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get(self,url):
            assert url.endswith(DATE)
            return Reply()
    con=open_db(str(tmp_path/"blender.sqlite"))
    snapshot={"games":fixtures()}
    with patch("nhl_true_blender_engine.dfo_dated_starters.httpx.AsyncClient",Client):
        report=asyncio.run(collect_dfo_goalies(con,snapshot,DATE,"PROJECTED"))
    assert report["matchedStarterIds"]==3
    rows=con.execute("SELECT * FROM evidence WHERE kind='GOALIE_STARTER'").fetchall()
    assert len(rows)==3
    attach(con,snapshot,DATE,"PROJECTED")
    assert snapshot["games"][0]["goalies"]["LAK"][0]["data"]["status"]=="EXPECTED"
    assert snapshot["games"][0]["goalies"]["BOS"][0]["data"]["status"]=="CONFIRMED"
    assert snapshot["games"][1]["goalies"]["TOR"][0]["data"]["goalieId"]=="301"
    assert not snapshot["games"][1]["goalies"]["CHI"]
    con.close()
