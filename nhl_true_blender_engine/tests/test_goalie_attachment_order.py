"""Regression: a physical goalie profile fetched BEFORE the starter report must attach."""
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.enrichment import ingest,attach
from nhl_true_blender_engine.engine import g0_full_slate

DATE="2026-11-15"
SRC="https://www.example.org/source"

def test_independent_scouting_is_joined_even_if_starter_arrives_later(tmp_path):
    db=open_db(str(tmp_path/"goalie.sqlite"))
    common={"slate_date":DATE,"stage":"PROJECTED","game_id":"5001",
            "source_url":SRC}
    ingest(db,{**common,"evidence_id":"physical-scouting","kind":"GOALIE_PROFILE",
        "observed_at":"2026-11-15T11:30:00Z",
        "payload":{"team":"BOS","goalieId":"88","status":"EXPECTED",
                   "weakZones":{"slot":{"sample":90}},
                   "strengthZones":{"point":{"sample":70}},
                   "sample":"90 independent zone observations",
                   "counterevidence":"strong point outcomes"}})
    ingest(db,{**common,"evidence_id":"starter-identity","kind":"GOALIE_STARTER",
        "observed_at":"2026-11-15T13:00:00Z",
        "payload":{"team":"BOS","goalieId":"88","status":"EXPECTED"}})
    game={"id":"5001","date":DATE,"away":"NYR","home":"BOS",
          "goalies":{},"rosters":{},"context":{},"coverage":{}}
    snapshot={"games":[game]}
    attach(db,snapshot,DATE,"PROJECTED")
    branch=game["goalies"]["BOS"][0]
    assert branch["data"]["goalieId"]=="88"
    assert "slot" in branch["data"]["weakZones"]
    assert branch["data"]["goalieProfileSourceUrl"]==SRC
    scan,notes=g0_full_slate(snapshot["games"],"PROJECTED")
    assert len(scan)==2
    assert scan[0]["goalieProfileEvidenced"] is True
    assert scan[1]["goalieProfileEvidenced"] is False
    db.close()
