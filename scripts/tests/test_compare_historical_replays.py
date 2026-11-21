"""Do not call differing replay snapshots an engine performance change."""
import json
from pathlib import Path

from scripts.compare_historical_replays import compare


def _row(date, snap, db, cutoff, legs, g0=None):
    return {
        "date": date, "status": "REPLAYED", "stage": "PROJECTED",
        "cutoff": cutoff, "snapshotSha256": snap, "evidenceDbSha256": db,
        "engineResult": {"card": {"current_legs": legs} if legs else None,
                         "g0TwoGoalieDirectionDecisions": g0 or {}},
    }


def _write(path, rows):
    Path(path).write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_frozen_input_mismatch_not_counted_as_scoring_change(tmp_path):
    prior = [{"gameId": "g1", "playerId": "p1"}]
    baseline = [
        _row("2026-11-10", "SAME-S", "SAME-DB", "2026-11-10T22:00:00Z", prior, {"g1": "A"}),
        _row("2026-11-17", "EARLY-S", "EARLY-DB", "2026-11-17T23:55:00Z", prior, {"g2": "X"}),
    ]
    patched = [
        _row("2026-11-10", "SAME-S", "SAME-DB", "2026-11-10T22:00:00Z", [], {"g1": "B"}),
        _row("2026-11-17", "LATE-S", "LATE-DB", "2026-11-18T00:55:00Z", [], {"g2": "Y"}),
    ]
    bp, pp, result = (tmp_path / name for name in ("baseline.jsonl","patched.jsonl","comparison.json"))
    _write(bp, baseline)
    _write(pp, patched)
    x = compare(bp, tmp_path/"none1", pp, tmp_path/"none2", result)
    assert x["sameInputRows"] == 1
    assert x["changedCoreDates"] == 1
    assert x["changedG0Dates"] == 1
    assert x["excludedComparisonDates"] == ["2026-11-17"]
    row = x["rows"][1]
    assert row["selectionInputsIdentical"] is False
    assert row["addedToCore"] == []
    assert row["removedFromCore"] == []
    assert row["excludedFromCausalComparison"] is True
    assert set(row["comparisonExclusionReason"]) == {
        "SNAPSHOT_HASH_DIFFERS","EVIDENCE_DB_HASH_DIFFERS","CUTOFF_OR_STAGE_DIFFERS"}
    assert row["uncomparableRawCoreDifference"] is True
    assert row["G0DirectionChanged"] is False
    assert json.loads(result.read_text())["changedCoreDates"] == 1


def test_matching_hash_but_different_cutoff_is_not_identical(tmp_path):
    b = [_row("2026-11-17","same","same","2026-11-17T20:00:00Z",
              [{"gameId":"g","playerId":"p"}])]
    p = [_row("2026-11-17","same","same","2026-11-17T21:00:00Z",[])]
    bp, pp = tmp_path/"b",tmp_path/"p"
    _write(bp,b);_write(pp,p)
    result=compare(bp,tmp_path/"missing0",pp,tmp_path/"missing1",tmp_path/"output.json")
    assert result["changedCoreDates"] == 0
    assert result["sameInputRows"] == 0
    assert result["excludedComparisonDates"] == ["2026-11-17"]
