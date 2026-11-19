"""Official NHL projected EV sources must not erase independently sourced PP."""
import tempfile
from pathlib import Path
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import attach, ingest


def _snapshot():
    return {"games":[{
        "id":"10","away":"COL","home":"UTA","goalies":{},"context":{},
        "coverage":{},
        "rosters":{"COL":{"sourceUrl":"https://api-web.nhle.com/v1/roster/COL/current",
                           "observedAt":"2026-11-19T12:00:00Z",
                           "data":{"team":"COL","players":[
                               {"id":"42","name":"Test Skater","position":"C",
                                "availability":"UNVERIFIED"}]}},
                   "UTA":{"sourceUrl":"https://api-web.nhle.com/v1/roster/UTA/current",
                           "observedAt":"2026-11-19T12:00:00Z",
                           "data":{"team":"UTA","players":[]}}}}]}


def _put(con,id,clock,source,payload):
    ingest(con,{"evidence_id":id,"slate_date":"2026-11-19",
                "stage":"PROJECTED","game_id":"10","player_id":"42",
                "kind":"PLAYER_DEPLOYMENT","source_url":source,
                "observed_at":clock,"payload":payload})


def test_same_ev_earlier_sourced_pp_unit_is_not_erased_by_official_projection():
    with tempfile.TemporaryDirectory() as folder:
        con=open_db(str(Path(folder)/"evidence.sqlite"))
        try:
            _put(con,"btl","2026-11-19T14:00:00Z",
                 "https://www.betweenthelineshockey.com/tonight.md",
                 {"EV":"F1","PP":1,"status":"PROJECTED"})
            _put(con,"nhl","2026-11-19T15:00:00Z",
                 "https://www.nhl.com/news/test",
                 {"EV":"F1","status":"PROJECTED","projectedNotConfirmed":True})
            snap=_snapshot()
            attach(con,snap,"2026-11-19","PROJECTED")
            person=snap["games"][0]["rosters"]["COL"]["data"]["players"][0]
            assert person["deployment"]["data"]["EV"]=="F1"
            assert person["deployment"]["data"]["PP"]==1
            assert person["deployment"]["sourceUrl"].startswith("https://www.betweenthelineshockey.com/")
            assert len(person["deployment"]["data"]["corroboratingProjectedEVSources"])==1
            assert person.get("deploymentConflict") is not True
        finally:
            con.close()


def test_later_independently_sourced_special_team_detail_can_be_attached():
    with tempfile.TemporaryDirectory() as folder:
        con=open_db(str(Path(folder)/"evidence.sqlite"))
        try:
            _put(con,"official","2026-11-19T14:00:00Z",
                 "https://www.nhl.com/news/test",
                 {"EV":"F1","status":"PROJECTED","projectedNotConfirmed":True})
            _put(con,"btl","2026-11-19T15:00:00Z",
                 "https://www.betweenthelineshockey.com/tonight.md",
                 {"EV":"F1","PP":2,"status":"PROJECTED"})
            snap=_snapshot()
            attach(con,snap,"2026-11-19","PROJECTED")
            player=snap["games"][0]["rosters"]["COL"]["data"]["players"][0]
            assert player["deployment"]["data"]["PP"]==2
            assert player["deployment"]["data"]["status"]=="PROJECTED"
        finally:
            con.close()
