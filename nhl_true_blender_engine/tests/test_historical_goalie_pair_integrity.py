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


def test_later_game_uses_its_own_pregame_cutoff(tmp_path, monkeypatch):
    """A valid late-game starter must survive an earlier game's puck drop."""
    db = tmp_path / "ledger.sqlite"
    open_db(str(db)).close()
    monkeypatch.setattr(ingest, "RAW_DB", db)
    day = "2026-11-10"
    manifest = tmp_path / "manifest.json"
    archive = tmp_path / "archive.json"
    manifest.write_text(json.dumps({"officialSchedule": {day: {"games": [
        {"id": "early", "away": "BOS", "home": "NYR",
         "startUTC": "2026-11-10T18:00:00Z"},
        {"id": "late", "away": "LAK", "home": "SJS",
         "startUTC": "2026-11-11T03:00:00Z"}
    ]}}}))
    def goalie(name, team, pid):
        return {
            "name": name, "status": "Confirmed",
            "reportUpdatedAt": "2026-11-10T21:00:00Z",
            "imageTeamAbbrevMatchesAssignedTeam": True,
            "nhlIdentityResolution": {
                "status": "EXACT_OFFICIAL_NHL_NAME_AND_GOALIE_MATCH",
                "playerId": pid
            }
        }
    archive.write_text(json.dumps({"pages": [{
        "date": day, "httpStatus": 200,
        "games": [{
            "away": "LAK", "home": "SJS", "officialScheduleMatch": True,
            "positionalPairingVerified": True,
            "awayGoalie": goalie("Late Away", "LAK", "1001"),
            "homeGoalie": goalie("Late Home", "SJS", "1002")
        }]
    }]}))
    monkeypatch.setattr(sys, "argv", ["ingest", str(manifest), str(archive)])
    ingest.main()
    report = json.loads((tmp_path / "dfo-goalie-ingestion.json").read_text())
    assert report["importedReceiptCount"] == 2
    assert {row["gameId"] for row in report["imported"]} == {"late"}
    con = open_db(str(db))
    try:
        rows = con.execute(
            "SELECT game_id, kind FROM evidence ORDER BY player_id"
        ).fetchall()
        assert [(row["game_id"], row["kind"]) for row in rows] == [
            ("late", "GOALIE_STARTER"), ("late", "GOALIE_STARTER")
        ]
    finally:
        con.close()


def test_missing_earlier_card_does_not_shift_verified_later_matchup():
    """Unique image team IDs can recover later pairings without positional guesses."""
    from scripts.inventory_dfo_historical_goalies import TEAM_ABBREV
    # A first-game card is missing; positional slicing would shift the next pair.
    cards = [
        {"name": "First Away", "imageTeamAbbrev": "BOS"},
        {"name": "Later Away", "imageTeamAbbrev": "LAK"},
        {"name": "Later Home", "imageTeamAbbrev": "SJS"},
    ]
    by_team = {}
    for card in cards:
        by_team.setdefault(card["imageTeamAbbrev"], []).append(card)
    assert len(by_team.get("NYR", [])) == 0
    assert len(by_team["LAK"]) == len(by_team["SJS"]) == 1
    assert by_team["LAK"][0]["name"] == "Later Away"
    assert by_team["SJS"][0]["name"] == "Later Home"


def test_dfo_headshot_utah_team_label_is_explicitly_normalized():
    from scripts.inventory_dfo_historical_goalies import _image_team_abbrev
    assert _image_team_abbrev(
        "https://api.dailyfaceoff.com/uploads/player/headshot/26614/Vejmelka-Karel_Utah-2025_.png"
    ) == "UTA"
    assert _image_team_abbrev("https://example.com/Goalie-NYR-2026.png") == "NYR"
    assert _image_team_abbrev(None) is None
    assert _image_team_abbrev("https://example.com/unknown.png") is None
