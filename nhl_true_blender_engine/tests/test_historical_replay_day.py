import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nhl_true_blender_engine import storage
from nhl_true_blender_engine.storage import open_db
from scripts.replay_historical_season import assert_database_as_of, replay_day
from nhl_true_blender_engine.tests.test_end_to_end_contract import fixture


def test_replay_day_issues_and_certifies_real_engine_card_with_wall_clock_after_puck(tmp_path, monkeypatch):
    snapshot = fixture()
    # Pin the fixture to a completed historical date while retaining the
    # real engine's future-state pregame contract.
    snapshot["games"][0]["date"] = "2026-11-17"
    snapshot["games"][0]["startUTC"] = "2026-11-17T00:00:00Z"
    game_start = datetime.fromisoformat(snapshot["games"][0]["startUTC"].replace("Z", "+00:00"))
    cutoff = game_start - timedelta(minutes=5)
    wall_after_puck = game_start + timedelta(hours=1)
    day = snapshot["games"][0]["date"]

    class PinnedWallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = wall_after_puck
            return value.replace(tzinfo=None) if tz is None else value.astimezone(tz)

    monkeypatch.setattr(storage, "datetime", PinnedWallClock)
    snapshot_bytes = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_bytes(snapshot_bytes)

    db_path = tmp_path / "evidence.sqlite"
    con = open_db(str(db_path))
    con.close()
    compressed = gzip.compress(db_path.read_bytes(), compresslevel=6, mtime=0)
    db_path.unlink()
    evidence_path = tmp_path / "evidence.sqlite.gz"
    evidence_path.write_bytes(compressed)

    bundle = {
        "stage": "CONFIRMED",
        "cutoff": cutoff.isoformat(),
        "inputs": [{
            "kind": "SYNTHETIC_PREGAME_FIXTURE",
            "source": "https://example.org/synthetic-contract-evidence",
            "availableAt": (cutoff - timedelta(hours=2)).isoformat(),
        }],
        "snapshot": snapshot_path.name,
        "snapshotSha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "evidenceDb": evidence_path.name,
        "evidenceDbSha256": hashlib.sha256(compressed).hexdigest(),
    }

    result = replay_day(tmp_path, day, None, bundle)
    card = result["engineResult"]["card"]
    assert card is not None
    assert len(card["current_legs"]) == 3
    assert result["gateCertification"]["selectedCoreOnlyFullyCertified"] is True
    assert result["historicalClockAppliedToEngineAndPersistence"] is True
    assert result["databaseObservedAtCutoffVerified"] is True
    assert result["databasePointInTimeVerified"] is False
    assert result["pointInTimeAudit"]["status"] == "PARTIAL_PROVIDER_ASOF_NOT_EXPOSED"
    assert datetime.fromisoformat(card["first_issued_at"]) <= cutoff.astimezone(storage.ET)
    assert PinnedWallClock.now(timezone.utc) > game_start
    assert result["engineResult"]["retroactiveCardMutation"] is False


@pytest.mark.parametrize(("table", "sql", "values"), [
    ("gates", "INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)",
     ("2026-11-17","PROJECTED","1","10","G0","PASS","{}","2026-11-17T10:00:00+00:00")),
    ("gate_history", "INSERT INTO gate_history VALUES (?,?,?,?,?,?,?,?,?,?)",
     ("hash","2026-11-17","PROJECTED","1","10","G0","PASS","{}","2026-11-17T10:00:00+00:00","2026-11-17T10:01:00+00:00")),
    ("jobs", "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
     ("run","2026-11-17","PROJECTED","2026-11-17T09:00:00+00:00",None,"COMPLETE","{}")),
    ("cards", "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?)",
     ("2026-11-17","card","[]","[]","PROJECTED","fingerprint",1,"2026-11-17T10:00:00+00:00","2026-11-17T10:00:00+00:00",None)),
    ("card_versions", "INSERT INTO card_versions VALUES (?,?,?,?,?,?,?,?,?)",
     ("version","2026-11-17","card",1,"PROJECTED","fingerprint","[]","{}","2026-11-17T10:00:00+00:00")),
    ("grades", "INSERT INTO grades VALUES (?,?,?,?,?,?,?)",
     ("card","2026-11-17","LOSS","[]","[]","[]","2026-11-18T00:00:00+00:00")),
    ("patches", "INSERT INTO patches VALUES (?,?,?,?,?,?)",
     ("old-patch","[]","{}","{}","{}","2026-11-17T10:00:00+00:00")),
    ("watch_events", "INSERT INTO watch_events VALUES (?,?,?,?,?,?,?,?,?)",
     ("event","2026-11-17","1","GOALIE","{}","{}","https://example.org","2026-11-17T10:00:00+00:00","[]")),
])
def test_replay_input_database_rejects_any_existing_production_state(tmp_path, table, sql, values):
    db = open_db(str(tmp_path / f"contaminated-{table}.sqlite"))
    cutoff = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    try:
        assert_database_as_of(db, cutoff, "2026-11-17")
        db.execute(sql, values)
        with pytest.raises(ValueError, match=f"contaminated: {table}"):
            assert_database_as_of(db, cutoff, "2026-11-17")
    finally:
        db.close()


def test_replay_input_database_rejects_future_and_non_pregame_evidence(tmp_path):
    db = open_db(str(tmp_path / "future.sqlite"))
    cutoff = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    try:
        storage.record_evidence(db, {
            "evidence_id": "future-row", "slate_date": "2026-11-17",
            "stage": "PROJECTED", "kind": "FIXTURE", "source_url": "https://example.org/future",
            "observed_at": (cutoff + timedelta(seconds=1)).isoformat(), "payload": {"fixture": True},
        })
        with pytest.raises(ValueError, match="post-cutoff"):
            assert_database_as_of(db, cutoff, '2026-11-17')
    finally:
        db.close()

    db = open_db(str(tmp_path / "postgame.sqlite"))
    try:
        storage.record_evidence(db, {
            "evidence_id": "postgame-row", "slate_date": "2026-11-17",
            "stage": "POSTGAME", "kind": "FIXTURE", "source_url": "https://example.org/postgame",
            "observed_at": (cutoff - timedelta(hours=1)).isoformat(), "payload": {"fixture": True},
        })
        with pytest.raises(ValueError, match="disallowed non-pregame"):
            assert_database_as_of(db, cutoff, '2026-11-17')
    finally:
        db.close()

def test_replay_input_database_rejects_same_day_historical_event_even_if_downloaded_early(tmp_path):
    db = open_db(str(tmp_path / "same-day-event.sqlite"))
    cutoff = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    try:
        storage.record_evidence(db, {
            "evidence_id": "same-day-game-log", "slate_date": "2026-11-17",
            "stage": "PROJECTED", "kind": "PLAYER_GAME_LOG",
            "source_url": "https://example.org/player-log",
            "observed_at": (cutoff - timedelta(hours=2)).isoformat(),
            "payload": {"appearances": [{"date": "2026-11-17", "goals": 1}]},
        })
        with pytest.raises(ValueError, match="same-day/future event dates"):
            assert_database_as_of(db, cutoff, "2026-11-17")
    finally:
        db.close()


def test_incomplete_season_replay_still_exports_gate_audit_without_grading_no_core(
        tmp_path, monkeypatch):
    """A failed G0/G2 historical replay must not erase its useful audit."""
    import sys
    from scripts.summarize_historical_replay import main, blocked_gate_reasons
    assert blocked_gate_reasons([
        "2026020003 G0 opposing goalie source missing",
        "2026020002 G2 official roster missing",
        "PRE_CORE_REVIEW: 0 qualified, G18 cannot choose",
    ]) == {"G0": 1, "G2": 1, "CORE_ASSEMBLY_UNRESOLVED": 1}
    manifest = {
        "start": "2026-09-29", "end": "2026-09-30",
        "scheduledDates": ["2026-09-29", "2026-09-30"],
        "verifiedOffDays": [],
        "officialSchedule": {
            "2026-09-29": {"games": [{"away": "AAA", "home": "BBB"}]},
            "2026-09-30": {"games": [{"away": "CCC", "home": "DDD"}]},
        },
        "slates": {"2026-09-29": {
            "providerAvailabilityTimeIndependentlyVerified": False}},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    selection = [
        {"date": "2026-09-29", "status": "REPLAYED",
         "gateDiagnostics": {"candidateGateMatrix": []},
         "engineResult": {"games": 1, "errors": [
             "2026020003 G0 both goalie profiles unavailable",
             "2026020002 G2 complete roster missing",
             "PRE_CORE_REVIEW: no Core issued"]}},
        {"date": "2026-09-30", "status": "SOURCE_BLOCKED",
         "reason": "No historical pregame bundle"},
    ]
    with (tmp_path / "selections.jsonl").open("w") as handle:
        for row in selection:
            handle.write(json.dumps(row) + "\n")
    with (tmp_path / "grades.jsonl").open("w") as handle:
        for day in ("2026-09-29", "2026-09-30"):
            handle.write(json.dumps({"date": day, "grade": {
                "status": "NO_CORE" if day.endswith("29") else "SOURCE_BLOCKED"}}) + "\n")
    output = tmp_path / "audit.json"
    argv = ["audit", str(tmp_path / "manifest.json"),
            str(tmp_path / "selections.jsonl"),
            str(tmp_path / "grades.jsonl"),
            str(tmp_path / "absent-postgame.jsonl"),
            str(tmp_path / "absent-comparison.json"), str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    report = json.loads(output.read_text())
    assert report["completion"]["fullyCompletedSlates"] == 0
    assert report["grading"]["gradedCards"] == 0
    assert report["blockerBreakdown"]["engineErrorCounts"] == {
        "G0": 1, "G2": 1, "CORE_ASSEMBLY_UNRESOLVED": 1,
        "OTHER_SOURCE_BLOCKER": 1}
    assert report["blockerBreakdown"]["scheduledSlatesWithUnverifiedProviderAvailability"] == 2
    assert report["blockerBreakdown"]["noCoreIsNotAnOfficiallyGradedLoss"] is True
    assert output.with_suffix(".md").exists()
