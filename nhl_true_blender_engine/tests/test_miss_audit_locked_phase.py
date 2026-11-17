"""Postgame audit must not confuse a later confirmed failure with issued Core proof."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import nhl_true_blender_engine.audit as audit
from nhl_true_blender_engine.engine import MASTER, OVERLAY
from nhl_true_blender_engine.storage import open_db

DATE = "2026-11-16"
GAME = "2026020331"
PLAYER = "8481540"
LOCK = "2026-11-16T18:45:00-05:00"
PREGAME = "2026-11-16T18:40:00-05:00"
LATER = "2026-11-16T19:00:00-05:00"
START = "2026-11-16T19:30:00-05:00"


def _setup(tmp_path, monkeypatch, stage="PROJECTED", confirmed_gap=True):
    db = open_db(str(tmp_path / "audit.sqlite"))
    leg = {"gameId": GAME, "playerId": PLAYER, "player": "Cole Caufield",
           "startUTC": "2026-11-17T00:30:00Z"}
    card = {"card_id": "NHL-2026-11-16-CANONICAL", "stage": stage,
            "first_issued_at": LOCK, "updated_at": LATER if stage == "CONFIRMED" else LOCK,
            "grade": {"hits": 0, "legs": 1, "result": "LOSS"},
            "current_legs": [leg]}
    monkeypatch.setattr(audit, "get_card", lambda con, date: card)
    db.execute("""INSERT INTO grades VALUES (?,?,?,?,?,?,?)""",
        (card["card_id"], DATE, "LOSS",
         json.dumps([{"gameId": GAME, "playerId": PLAYER,
                      "player": leg["player"], "result": "MISS", "goals": 0}]),
         json.dumps(["https://api-web.nhle.com/v1/score/2026-11-16"]),
         "[]", "2026-11-17T03:00:00-05:00"))
    # Original projected source-backed gate matrix is archived when another
    # pregame attempt overwrites the stage's active gate table.
    for index, gate in enumerate(MASTER + OVERLAY):
        details = json.dumps({"evidence": {"test": "source-backed"},
                              "sourceIds": ["https://api-web.nhle.com/v1/score/2026-11-16"]})
        db.execute("""INSERT INTO gate_history VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (f"original-{index}", DATE, "PROJECTED", GAME, PLAYER,
           gate, "PASS", details, PREGAME, "2026-11-16T19:02:00-05:00"))
        db.execute("""INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)""",
          (DATE, "CONFIRMED", GAME, PLAYER, gate,
           "NOT_EXECUTED" if gate == "G2" and confirmed_gap else "PASS",
           details, LATER))
    return db


def test_projected_locked_misses_ignore_later_confirmed_g2_gap(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    # Exercise correction of the already-saved incorrect cross-phase finding.
    audit.configure_audit_table(db)
    db.execute("""INSERT INTO miss_audits VALUES (?,?,?,?,?,?,?,?,?)""",
       (DATE, GAME, PLAYER, "NHL-2026-11-16-CANONICAL",
        "PREGAME_GATE_RECEIPT_INCOMPLETE", "G2", "[]", "{}",
        "2026-11-17T03:00:00-05:00"))
    result = audit.audit_misses(db, DATE)
    assert result[0]["auditStage"] == "PROJECTED"
    assert result[0]["originalLockReceiptCount"] == len(MASTER + OVERLAY)
    assert result[0]["earliestGate"] is None
    assert result[0]["conclusion"] == "MISS_WITHOUT_PROVEN_PREGAME_GATE_DEFECT"
    row = db.execute("SELECT * FROM miss_audits").fetchone()
    assert row["earliest_gate"] is None
    details = json.loads(row["source_comparison"])
    assert details["previousCrossPhaseAuditCorrected"]["earliestGate"] == "G2"
    assert details["archivedPregameRowsConsidered"] == len(MASTER + OVERLAY)
    db.close()


def test_confirmed_locked_card_keeps_actual_confirmed_gap(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch, stage="CONFIRMED")
    result = audit.audit_misses(db, DATE)
    assert result[0]["auditStage"] == "CONFIRMED"
    assert result[0]["earliestGate"] == "G2"
    assert result[0]["conclusion"] == "ORIGINAL_LOCK_GATE_RECEIPTS_UNVERIFIED"
    assert result[0]["patchesToAudit"] == []
    db.close()


def test_postissuance_gate_row_cannot_change_locked_audit(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    db.execute("""INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)""",
          (DATE, "PROJECTED", GAME, PLAYER, "G2", "NOT_EXECUTED",
           "{}", "2026-11-16T19:01:00-05:00"))
    result = audit.audit_misses(db, DATE)
    assert result[0]["earliestGate"] is None
    assert result[0]["originalLockReceiptCount"] == len(MASTER + OVERLAY)
    db.close()
