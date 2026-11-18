"""Regression: historical goalie receipts require unambiguous matchup pairing."""
import json
import sys

from nhl_true_blender_engine.storage import open_db
from scripts import ingest_dfo_goalie_evidence as ingest


def test_ambiguous_pairing_never_enters_canonical_ledger(tmp_path, monkeypatch):
    db = tmp_path / "ledger.sqlite"
    con = open_db(str(db))
    con.close()
    monkeypatch.setattr(ingest, "RAW_DB", db)
    day = "2026-11-10"
    manifest = tmp_path / "manifest.json"
    archive = tmp_path / "archive.json"
    manifest.write_text(json.dumps({
        "officialSchedule": {day: {"games": [{
            "id": "2026020222", "away": "BOS", "home": "NYR",
            "startTimeUTC": "2026-11-11T00:00:00Z"
        }]}}
    }))
    goalie = {
        "name": "Test Goalie", "status": "Confirmed",
        "reportUpdatedAt": "2026-11-10T16:00:00Z",
        "imageTeamAbbrevMatchesAssignedTeam": True,
        "nhlIdentityResolution": {
            "status": "EXACT_OFFICIAL_NHL_NAME_AND_GOALIE_MATCH",
            "playerId": "12345"
        }
    }
    archive.write_text(json.dumps({"pages": [{
        "date": day, "httpStatus": 200,
        "games": [{
            "away": "BOS", "home": "NYR", "officialScheduleMatch": True,
            "positionalPairingVerified": False,
            "awayGoalie": goalie, "homeGoalie": goalie
        }]
    }]}))
    monkeypatch.setattr(sys, "argv", ["ingest", str(manifest), str(archive)])
    ingest.main()
    report = json.loads((tmp_path / "dfo-goalie-ingestion.json").read_text())
    assert report["importedReceiptCount"] == 0
    assert any(row["reason"] == "GOALIE_PAIR_SEQUENCE_NOT_VERIFIED"
               for row in report["rejected"])
    con = open_db(str(db))
    try:
        assert con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 0
    finally:
        con.close()
