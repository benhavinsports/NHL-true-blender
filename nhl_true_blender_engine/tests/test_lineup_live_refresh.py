"""One live text adapter must feed independent select AND hourly watch."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import httpx
import pytest
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import attach
from nhl_true_blender_engine.lineup_parser import fetch_and_ingest_lineups,unique_official_player
from nhl_true_blender_engine.engine import all_goalie_branches

@pytest.mark.asyncio
async def test_multi_game_live_source_attaches_all_real_starter_identities(tmp_path,monkeypatch):
    date=datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    text=f"""# Tonight in the NHL: line combinations and starting goalies (games dated {date})
## Edmonton Oilers at Philadelphia Flyers
Starting goalies:
- Tristan Jarry (EDM), Unconfirmed
- Dan Vladar (PHI), Confirmed
### Edmonton Oilers
Forward lines:
1. Leon Draisaitl – Connor McDavid – Zach Hyman
Power play 1: Leon Draisaitl – Connor McDavid – Zach Hyman
Injuries:
- Another Player (C, Injured Reserve)
## Calgary Flames at Anaheim Ducks
Starting goalies:
- Dustin Wolf (CGY), Unconfirmed
- Lukas Dostal (ANA), Unconfirmed
### Anaheim Ducks
Forward lines:
1. Leo Carlsson – Troy Terry – Cutter Gauthier
Injuries:
- Injured Player (D, Injured Reserve)
"""
    orig=httpx.AsyncClient
    def fake_client(*args,**kwargs):
        return orig(*args,transport=httpx.MockTransport(
            lambda req:httpx.Response(200,text=text)),**kwargs)
    monkeypatch.setattr(httpx,"AsyncClient",fake_client)
    def roster(players,goalies):
        return {"data":{"players":[{"id":str(i),"name":n,"position":"C"}
                                     for i,n in players],
                        "goalies":[{"id":str(i),"name":n} for i,n in goalies]}}
    games=[
        {"id":"1000","away":"EDM","home":"PHI","goalies":{},
         "rosters":{"EDM":roster([(10,"Leon Draisaitl"),(11,"Connor McDavid"),
                                  (12,"Zach Hyman")],[(20,"Tristan Jarry")]),
                    "PHI":roster([],[(21,"Dan Vladar")])},"coverage":{}},
        {"id":"1001","away":"CGY","home":"ANA","goalies":{},
         "rosters":{"CGY":roster([],[(22,"Dustin Wolf")]),
                    "ANA":roster([(30,"Leo Carlsson"),(31,"Troy Terry"),
                                  (32,"Cutter Gauthier")],[(23,"Lukas Dostal")])},
         "coverage":{}}
    ]
    con=open_db(str(tmp_path/"lineup.sqlite"))
    result=await fetch_and_ingest_lineups(con,{"games":games},date,"CONFIRMED")
    assert result["status"]=="DATED_SOURCE_PARSED"
    assert result["goalieReports"]==4
    assert result["deploymentRecords"]==6
    attach(con,{"games":games},date,"CONFIRMED")
    a=all_goalie_branches(games[0],"CONFIRMED")
    assert a["EDM"][0]["data"]["status"]=="EXPECTED"
    assert a["PHI"][0]["data"]["status"]=="CONFIRMED"
    assert all_goalie_branches(games[1],"CONFIRMED")["ANA"][0]["data"]["status"]=="EXPECTED"
    assert games[0]["rosters"]["EDM"]["data"]["players"][0]["deployment"]["data"]["status"]=="PROJECTED"
    con.close()

def test_unique_official_nickname_variant_must_have_exact_surname_and_unique_id():
    roster=[{"id":"10","name":"Zachary Bolduc"},
            {"id":"11","name":"Gabriel Perreault"},
            {"id":"12","name":"Benjamin McCartney"}]
    assert unique_official_player("Zack Bolduc",roster)["id"]=="10"
    assert unique_official_player("Gabe Perreault",roster)["id"]=="11"
    assert unique_official_player("Ben McCartney",roster)["id"]=="12"
    assert unique_official_player("Zack Bolduc",roster,("10",)) is None


def test_collision_does_not_guess_which_elias_pettersson_is_dressed():
    roster=[{"id":"20","name":"Elias Nils Pettersson"},
            {"id":"21","name":"Elias Carl Pettersson"}]
    assert unique_official_player("Elias Pettersson",roster) is None


def test_goalie_first_name_variant_reconciles_only_unique_official_roster_id(tmp_path):
    from nhl_true_blender_engine.lineup_parser import ingest_lineups
    from json import loads
    markdown = """# Tonight in the NHL: line combinations and starting goalies (games dated 2026-11-17)
## Edmonton Oilers at Philadelphia Flyers
Starting goalies:
- Dan Vladar (PHI), Unconfirmed
- Tristan Jarry (EDM), Unconfirmed
"""
    def official(goalies):
        return {"data":{"players":[],"goalies":goalies}}
    game={"id":"g1","away":"EDM","home":"PHI",
          "goalies":{"EDM":[],"PHI":[]},
          "rosters":{"EDM":official([{"id":"100","name":"Tristan Jarry"}]),
                     "PHI":official([{"id":"200","name":"Daniel Vladar"}])}}
    con=open_db(str(tmp_path/"alias.sqlite"))
    try:
        result=ingest_lineups(con,{"games":[game]},"2026-11-17","PROJECTED",
                              markdown,"2026-11-17T17:00:00Z")
        assert result["goalieReports"]==2
        assert result["matchedGoalieReports"]==2
        assert result["unmatchedGoalieReports"]==0
        rows=con.execute("SELECT payload FROM evidence WHERE kind='GOALIE_STARTER'").fetchall()
        ids={str(loads(row["payload"])["goalieId"]) for row in rows}
        assert ids=={"100","200"}
        assert all(loads(row["payload"])["status"]=="EXPECTED" for row in rows)
        # An ambiguous nickname cannot establish either official goalie ID.
        game["rosters"]["PHI"]["data"]["goalies"].append(
            {"id":"201","name":"Dany Vladar"})
        con.execute("DELETE FROM evidence")
        result=ingest_lineups(con,{"games":[game]},"2026-11-17","PROJECTED",
                              markdown,"2026-11-17T17:01:00Z")
        assert result["matchedGoalieReports"]==1
        assert result["unmatchedGoalieReports"]==1
        assert any(x.get("reason")=="OFFICIAL_GOALIE_ID_UNMATCHED_OR_AMBIGUOUS"
                   for x in result["unmatched"])
        ids={str(loads(row["payload"])["goalieId"]) for row in
             con.execute("SELECT payload FROM evidence WHERE kind='GOALIE_STARTER'")}
        assert ids=={"100"}
    finally:
        con.close()


def _deployment_fixture():
    return {"games":[{"id":"900","away":"AAA","home":"BBB",
        "goalies":{"AAA":[],"BBB":[]},"coverage":{},
        "rosters":{"AAA":{"data":{"players":[{"id":"99","name":"Fixture Forward","position":"C"}]}},
                   "BBB":{"data":{"players":[]}}}}]}


def _put_deployment(con, evidence_id, stage, observed, status, line):
    from nhl_true_blender_engine.enrichment import ingest
    ingest(con,{"evidence_id":evidence_id,"slate_date":"2026-11-19",
        "stage":stage,"game_id":"900","player_id":"99",
        "kind":"PLAYER_DEPLOYMENT","source_url":"https://example.com/"+evidence_id,
        "observed_at":observed,"payload":{"EV":line,"status":status,
        "sourceType":"INDEPENDENT_LINEUP_TEST_RECEIPT"}})


def test_confirmed_role_resolves_earlier_conflicting_projected_assignments(tmp_path):
    con=open_db(str(tmp_path/"confirmed-role.sqlite"))
    try:
        _put_deployment(con,"early","PROJECTED","2026-11-19T12:00:00Z","PROJECTED","F1")
        _put_deployment(con,"disagree","PROJECTED","2026-11-19T12:01:00Z","PROJECTED","F2")
        _put_deployment(con,"confirmed","CONFIRMED","2026-11-19T12:02:00Z","CONFIRMED","F3")
        snap=_deployment_fixture()
        attach(con,snap,"2026-11-19","CONFIRMED")
        skater=snap["games"][0]["rosters"]["AAA"]["data"]["players"][0]
        assert not skater.get("deploymentConflict")
        assert skater["deployment"]["data"]["status"]=="CONFIRMED"
        assert skater["deployment"]["data"]["EV"]=="F3"
        assert skater["deployment"]["data"]["supersededProjectedConflict"]["conflictingSourceCount"]==1
    finally:
        con.close()


def test_disagreeing_confirmed_role_receipts_cannot_silently_pass_g6(tmp_path):
    con=open_db(str(tmp_path/"confirmed-conflict.sqlite"))
    try:
        _put_deployment(con,"first","CONFIRMED","2026-11-19T12:00:00Z","CONFIRMED","F1")
        _put_deployment(con,"second","CONFIRMED","2026-11-19T12:01:00Z","CONFIRMED","F2")
        snap=_deployment_fixture()
        attach(con,snap,"2026-11-19","CONFIRMED")
        skater=snap["games"][0]["rosters"]["AAA"]["data"]["players"][0]
        assert skater["deploymentConflict"] is True
        assert skater["deployment"]["data"]["EV"]=="F1"
        assert len(skater["deployment"]["data"]["conflictingConfirmedAssignments"])==1
    finally:
        con.close()
