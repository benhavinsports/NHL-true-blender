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
    assert datetime.now(timezone.utc) > game_start
    assert result["engineResult"]["retroactiveCardMutation"] is False


def test_replay_input_database_rejects_existing_card_grade_patch_or_gate_state(tmp_path):
    db = open_db(str(tmp_path / "contaminated.sqlite"))
    cutoff = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    try:
        assert_database_as_of(db, cutoff, '2026-11-17')
        db.execute(
            "INSERT INTO patches VALUES (?,?,?,?,?,?)",
            ("old-outcome-patch", "[]", "{}", "{}", "{}", cutoff.isoformat()),
        )
        with pytest.raises(ValueError, match="contaminated: patches"):
            assert_database_as_of(db, cutoff)
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
            assert_database_as_of(db, cutoff)
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
            assert_database_as_of(db, cutoff)
    finally:
        db.close()
