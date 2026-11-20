"""Postgame audit must not confuse a later confirmed failure with issued Core proof."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import nhl_true_blender_engine.audit as audit
from nhl_true_blender_engine.engine import MASTER, OVERLAY, STEPS_BY_GATE
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
            "current_legs": [leg], "fingerprint": "synthetic-fingerprint", "revision": 1}
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


def test_mixed_card_reads_confirmed_research_without_promoting_source_status(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch, stage='MIXED', confirmed_gap=False)
    db.execute('UPDATE gates SET evaluated_at=?', (PREGAME,))
    card = audit.get_card(db, DATE)
    rows, scope = audit._issued_gate_receipts(db, DATE, card, card['current_legs'][0])
    assert len(rows) == len(MASTER + OVERLAY)
    assert scope['stage'] == 'CONFIRMED'
    assert scope['cardEvidenceStage'] == 'MIXED'
    assert card['stage'] == 'MIXED'
    db.close()


def test_frozen_leg_audit_uses_its_own_pre_puck_card_version(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch, stage='MIXED')
    card = audit.get_card(db, DATE)
    card['updated_at'] = '2026-11-16T20:00:00-05:00'
    for revision, stage, clock in [(1, 'PROJECTED', LOCK),
                                   (2, 'MIXED', card['updated_at'])]:
        db.execute('INSERT INTO card_versions VALUES (?,?,?,?,?,?,?,?,?)',
                   (f'v{revision}', DATE, card['card_id'], revision, stage,
                    card['fingerprint'], json.dumps(card['current_legs']), '{}', clock))
    rows, scope = audit._issued_gate_receipts(db, DATE, card, card['current_legs'][0])
    assert len(rows) == len(MASTER + OVERLAY)
    assert scope['stage'] == 'PROJECTED'
    assert scope['issuedAt'] == LOCK
    assert all(r['disposition'] == 'PASS' for r in rows.values())
    db.close()


def test_unified_original_functions_are_audited_without_invented_extra_gate_rows(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    db.execute("DELETE FROM gate_history WHERE gate LIKE 'Step%'")
    for gate, steps in STEPS_BY_GATE.items():
        functions = [{'step': step, 'disposition': 'PASS',
                      'sourceIds': ['https://nhl.com/source'],
                      'evidence': {'independentOverlayEvaluation': True,
                                   'checkedBeforeG18': True,
                                   'masterGateVerdictCopied': False}} for step in steps]
        db.execute('UPDATE gate_history SET details=? WHERE gate=?',
                   (json.dumps({'evidence': {'originalFunctionEvidence': functions}}), gate))
    card = audit.get_card(db, DATE)
    rows, _ = audit._issued_gate_receipts(db, DATE, card, card['current_legs'][0])
    assert len(rows) == len(MASTER + OVERLAY)
    assert db.execute('SELECT COUNT(*) FROM gate_history').fetchone()[0] == len(MASTER)
    # A failed internal function cannot inherit its owning gate's PASS.
    detail = json.loads(db.execute("SELECT details FROM gate_history WHERE gate='G4'").fetchone()[0])
    detail['evidence']['originalFunctionEvidence'][0]['disposition'] = 'NOT_EXECUTED'
    db.execute("UPDATE gate_history SET details=? WHERE gate='G4'", (json.dumps(detail),))
    rows, _ = audit._issued_gate_receipts(db, DATE, card, card['current_legs'][0])
    failed = detail['evidence']['originalFunctionEvidence'][0]['step']
    assert rows[failed]['disposition'] == 'NOT_EXECUTED'
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



def test_official_recipient_conflict_is_carried_into_immutable_miss_audit(tmp_path, monkeypatch):
    db=_setup(tmp_path,monkeypatch)
    recipient_audit={
        "status":"OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON",
        "cardId":"NHL-2026-11-16-CANONICAL",
        "originalFingerprint":"synthetic-fingerprint","originalRevision":1,
        "officialSourceUrls":["https://api-web.nhle.com/v1/score/2026-11-16"],
        "selectedLegs":[{
            "gameId":GAME,"lockedPlayerId":PLAYER,"lockedPlayer":"Cole Caufield",
            "auditFlags":[
                "SCORING_TEAMMATE_WAS_PREGAME_G105_DEFEATED_RETROSPECTIVELY",
                "OPPOSITE_G0_DIRECTION_SCORED_MORE_POSTGAME_ONLY"],
            "sameAttackSideGoals":1,"oppositeAttackSideGoals":3,
            "officialScorers":[{
                "player":"Synthetic Teammate","playerId":"999","goals":1,
                "sameAttackDirectionAsCore":True,"pregameG105Verdict":"DEFEATED",
                "pregameG105ChallengerEvidence":{"sameLane":True}}],
            "prePuckGateReceipts":{"G0":{"status":"PASS"},"G10.5":{"status":"PASS"}}
        }]
    }
    result=audit.audit_misses(db,DATE,recipient_audit=recipient_audit)
    assert result[0]["conclusion"]=="PREGAME_GATE_REPLAY_REQUIRED"
    assert result[0]["earliestGate"]=="G0"
    assert result[0]["reviewTargets"]==["G0","G10.5"]
    row=db.execute("SELECT conclusion,earliest_gate,source_comparison FROM miss_audits").fetchone()
    assert row["conclusion"]=="PREGAME_GATE_REPLAY_REQUIRED"
    assert row["earliest_gate"]=="G0"
    assert json.loads(row["source_comparison"])["recipientAuditReview"]["doesNotActivateAPatchByItself"] is True
    assert db.execute("SELECT COUNT(*) FROM patches").fetchone()[0]==0
    db.close()
