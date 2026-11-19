"""Historical replay goalie profiles must honor the slate cutoff, not the starter clock."""
import sqlite3

from scripts.build_replay_bundles import _historical_goalie_profile_candidates


def test_profile_after_starter_but_before_first_puck_is_eligible():
    # Two independently observed sources: starter 14:00Z, profile 16:00Z.
    # A prior check against starter time falsely removed the valid profile.
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        con.execute(
            "CREATE TABLE evidence (kind TEXT, slate_date TEXT, "
            "observed_at TEXT, evidence_id TEXT)"
        )
        con.executemany(
            "INSERT INTO evidence (kind, slate_date, observed_at, evidence_id) "
            "VALUES (?, ?, ?, ?)",
            [
                ("GOALIE_STARTER", "2026-11-17", "2026-11-17T14:00:00Z", "starter"),
                ("GOALIE_PROFILE", "2026-11-16", "2026-11-16T20:00:00Z", "prior"),
                ("GOALIE_PROFILE", "2026-11-17", "2026-11-17T16:00:00Z", "later-than-starter"),
                ("GOALIE_PROFILE", "2026-11-17", "2026-11-17T23:56:00Z", "post-cutoff"),
                ("GOALIE_PROFILE", "2026-11-18", "2026-11-17T17:00:00Z", "future-slate"),
            ],
        )
        rows = _historical_goalie_profile_candidates(
            con, "2026-11-17", "2026-11-17T23:55:00Z"
        )
        assert [row["evidence_id"] for row in rows] == [
            "later-than-starter", "prior"
        ]
    finally:
        con.close()
