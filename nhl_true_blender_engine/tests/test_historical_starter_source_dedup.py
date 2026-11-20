"""Repeated starter receipts do not multiply historical goalie profiles."""
import json
import sqlite3
from datetime import datetime, timezone

from scripts.reconstruct_historical_pbp import _target_starters


def test_dedupe_exact_historical_source_branch_but_keep_real_goalie_disagreement():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.execute(
            "CREATE TABLE evidence (slate_date TEXT, kind TEXT, stage TEXT, "
            "game_id TEXT, observed_at TEXT, source_url TEXT, payload TEXT)"
        )
        def put(goalie_id, observed, source, *, team="NYR", status="EXPECTED",
                stage="PROJECTED"):
            con.execute(
                "INSERT INTO evidence VALUES (?,?,?,?,?,?,?)",
                ("2026-11-17", "GOALIE_STARTER", stage, "fixture-game",
                 observed, source, json.dumps({
                     "goalieId": goalie_id, "team": team, "status": status
                 })),
            )
        a = "https://example.org/starter-a"
        b = "https://example.org/starter-b"
        put("111", "2026-11-17T13:00:00Z", a)
        put("111", "2026-11-17T15:00:00Z", a)
        put("111", "2026-11-17T16:00:00Z", b)
        put("222", "2026-11-17T16:30:00Z", a)
        put("222", "2026-11-17T17:00:00Z", a, status="CONFIRMED",
            stage="CONFIRMED")
        put("333", "2026-11-17T22:00:00Z", a)  # After the slate cutoff.
        games = [{"id": "fixture-game", "away": "NYR", "home": "BOS", "startTimeUTC":"2026-11-17T23:00:00Z"}]
        cutoff = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)
        result = _target_starters(con, "2026-11-17", games, cutoff)
        rows = {(d["goalieId"], d["status"], row["source_url"]): row
                for row, d in result}
        assert len(result) == 4
        assert rows[("111", "EXPECTED", a)]["observed_at"] == (
            "2026-11-17T15:00:00Z")
        assert ("111", "EXPECTED", b) in rows
        assert ("222", "EXPECTED", a) in rows
        assert ("222", "CONFIRMED", a) in rows
        assert all(d["goalieId"] != "333" for _, d in result)
    finally:
        con.close()
