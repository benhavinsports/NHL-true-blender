import json
from datetime import datetime, timezone

from scripts.build_replay_bundles import build_day
from nhl_true_blender_engine.storage import open_db, record_evidence


def test_build_day_does_not_require_saved_engine_job_or_card(tmp_path):
    db_path = tmp_path / "archive.sqlite"
    con = open_db(str(db_path))
    try:
        observed = "2026-10-01T18:00:00Z"
        record_evidence(con, {
            "evidence_id": "dated-context-1",
            "slate_date": "2026-10-01",
            "stage": "OFFICIAL",
            "game_id": "2026020001",
            "kind": "MATCH_CONTEXT",
            "source_url": "https://example.test/context",
            "observed_at": observed,
            "payload": {
                "awayLastGameDate": "2026-09-29",
                "homeLastGameDate": "2026-09-29"
            }
        })
        # Deliberately create no jobs or cards: neither is a valid prerequisite
        # for reconstructing a historical slate from dated evidence.
        schedule_row = {
            "source": "https://api-web.nhle.com/v1/score/2026-10-01",
            "downloadedAt": "2026-10-01T17:00:00Z",
            "games": [{
                "id": "2026020001", "away": "BOS", "home": "NYR",
                "startTimeUTC": "2026-10-01T23:00:00Z"
            }]
        }
        bundle = build_day(con, "2026-10-01", tmp_path / "out", schedule_row)
        assert bundle is not None
        assert bundle["stage"] == "PROJECTED"
        assert bundle["cutoff"] == "2026-10-01T22:55:00Z"
        snapshot = json.loads((tmp_path / "out" / bundle["snapshot"]).read_text())
        assert [(g["id"], g["away"], g["home"]) for g in snapshot["games"]] == [
            ("2026020001", "BOS", "NYR")
        ]
        assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0
    finally:
        con.close()


def test_goalie_confirmation_does_not_implicitly_confirm_skaters(tmp_path):
    """Point-in-time verified goalie status is independent of skater confirmation."""
    db = open_db(str(tmp_path / "archive.sqlite"))
    day, game_id, observed = "2026-10-01", "2026020001", "2026-10-01T18:00:00Z"
    try:
        for team, goalie in (("BOS", "8481111"), ("NYR", "8482222")):
            record_evidence(db, {
                "evidence_id": f"dated-confirmed-{team}",
                "slate_date": day, "stage": "CONFIRMED",
                "game_id": game_id, "player_id": goalie,
                "kind": "GOALIE_STARTER",
                "source_url": f"https://example.test/{team}/goalie",
                "observed_at": observed,
                "payload": {"team": team, "goalieId": goalie,
                            "status": "CONFIRMED", "identityMatched": True},
            })
        # There is no confirmed dressed lineup or confirmed EV deployment.
        # This cannot become a CONFIRMED skater replay merely because BOTH
        # goalies were independently reported confirmed before puck drop.
        schedule = {
            "source": "https://api-web.nhle.com/v1/score/2026-10-01",
            "games": [{
                "id": game_id, "away": "BOS", "home": "NYR",
                "startTimeUTC": "2026-10-01T23:00:00Z",
            }],
        }
        bundle = build_day(db, day, tmp_path / "out", schedule)
        assert bundle["stage"] == "PROJECTED"
        saved = json.loads((tmp_path / "out" / bundle["snapshot"]).read_text())
        goalie_branches = saved["games"][0]["goalies"]
        assert {team: [(b["data"]["goalieId"], b["data"]["status"])
                       for b in goalie_branches[team]]
                for team in ("BOS", "NYR")} == {
            "BOS": [("8481111", "CONFIRMED")],
            "NYR": [("8482222", "CONFIRMED")],
        }
    finally:
        db.close()


def test_carries_independent_goalie_profile_without_rewriting_identity(tmp_path):
    """A prior pre-cutoff profile must be serializable and attach to the new verified starter ID."""
    con = open_db(str(tmp_path / "evidence.sqlite"))
    try:
        record_evidence(con, {
            "evidence_id": "archived-goalie-profile",
            "slate_date": "2026-10-01",
            "stage": "OFFICIAL",
            "game_id": "2026020001",
            "kind": "GOALIE_PROFILE",
            "source_url": "https://example.test/independent-goalie-analysis",
            "observed_at": "2026-10-01T18:00:00Z",
            "payload": {
                "team": "NYR", "goalieId": "12345",
                "sample": {"shots": 50}, "counterevidence": {"shots": 50},
                "weakZones": {"left": {"status": "EVIDENCED_RELATIVE_WEAKNESS"}},
                "strengthZones": {}, "sourceReviewed": True,
            },
        })
        record_evidence(con, {
            "evidence_id": "dated-starter-on-next-slate",
            "slate_date": "2026-10-02",
            "stage": "PROJECTED",
            "game_id": "2026020002",
            "kind": "GOALIE_STARTER",
            "source_url": "https://example.test/dated-starter",
            "observed_at": "2026-10-02T18:00:00Z",
            "payload": {"team": "NYR", "goalieId": "12345", "status": "EXPECTED"},
        })
        bundle = build_day(con, "2026-10-02", tmp_path / "out", {
            "source": "https://api-web.nhle.com/v1/score/2026-10-02",
            "downloadedAt": "2026-10-02T17:00:00Z",
            "games": [{
                "gameId": "2026020002", "away": "BOS", "home": "NYR",
                "startTimeUTC": "2026-10-02T23:00:00Z",
            }],
        })
        assert bundle["historicalGoalieProfileCarryForwardCount"] == 1
        snapshot = json.loads((tmp_path / "out" / bundle["snapshot"]).read_text())
        goalie = snapshot["games"][0]["goalies"]["NYR"][0]
        assert goalie["data"]["goalieId"] == "12345"
        assert goalie["data"]["status"] == "EXPECTED"
        assert goalie["data"]["goalieProfileSourceUrl"] == "https://example.test/independent-goalie-analysis"
        assert goalie["data"]["goalieProfileObservedAt"] == "2026-10-01T18:00:00Z"
        assert goalie["data"]["goalieProfileEvidenceId"].startswith("replay-carry-")
        assert bundle["inputs"]
    finally:
        con.close()
