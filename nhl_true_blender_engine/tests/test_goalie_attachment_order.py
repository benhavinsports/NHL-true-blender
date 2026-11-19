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


def test_projected_research_retains_actual_confirmed_goalie_without_confirming_skaters(tmp_path):
    """Real goalie source status must not be confused with entire run phase."""
    db=open_db(str(tmp_path/"confirmed-goalie.sqlite"))
    common={"slate_date":DATE,"stage":"CONFIRMED","game_id":"5001",
            "source_url":SRC,"observed_at":"2026-11-15T13:00:00Z"}
    ingest(db,{**common,"evidence_id":"confirmed-goalie","kind":"GOALIE_STARTER",
        "payload":{"team":"BOS","goalieId":"88","status":"CONFIRMED"}})
    ingest(db,{**common,"evidence_id":"confirmed-goalie-profile","kind":"GOALIE_PROFILE",
        "payload":{"team":"BOS","goalieId":"88","status":"CONFIRMED",
                   "weakZones":{"Low Slot":{"shotsAgainst":42}},
                   "strengthZones":{"High Slot":{"shotsAgainst":52}},
                   "sample":{"shotsAgainst":94},"counterevidence":{"reviewed":True}}})
    ingest(db,{**common,"evidence_id":"confirmed-player-status",
        "player_id":"123","kind":"PLAYER_STATUS",
        "payload":{"status":"DRESSED"}})
    player={"id":"123","name":"Test Player","availability":"UNVERIFIED"}
    game={"id":"5001","date":DATE,"away":"NYR","home":"BOS",
          "goalies":{},"rosters":{"BOS":{"sourceUrl":SRC,
                    "observedAt":"2026-11-15T12:00:00Z",
                    "data":{"team":"BOS","players":[player]}}},
          "context":{},"coverage":{}}
    attach(db,{"games":[game]},DATE,"PROJECTED")
    branch=game["goalies"]["BOS"][0]
    assert branch["data"]["status"]=="CONFIRMED"
    assert branch["data"]["weakZones"]["Low Slot"]["shotsAgainst"]==42
    assert player["availability"]=="UNVERIFIED", "CONFIRMED skater data cannot leak into projected"
    db.close()
