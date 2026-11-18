import json

from scripts.run_cycle import _publish_official_grade


def test_publishes_read_only_miss_audit_without_changing_frozen_card(tmp_path):
    date = "2026-11-17"
    card_id = "NHL-2026-11-17-CANONICAL"
    legs = [
        {"gameId": "2026020335", "playerId": "8477933",
         "player": "Sam Reinhart", "path": "PRIMARY"}
    ]
    card_path = tmp_path / "site_cards" / f"{date}.json"
    card_path.parent.mkdir(parents=True)
    original = {
        "cardId": card_id,
        "fingerprint": "immutable-fingerprint",
        "revision": 3,
        "legsJson": json.dumps(legs),
        "gradeJson": "",
        "auditJson": "",
        "status": "FROZEN",
    }
    card_path.write_text(json.dumps(original), encoding="utf-8")

    grade = {
        "card_id": card_id,
        "graded_at": "2026-11-18T03:40:57-05:00",
        "result": "LOSS",
        "legs": [{
            "gameId": "2026020335", "playerId": "8477933",
            "player": "Sam Reinhart", "goals": 0, "result": "MISS"
        }],
        "official_sources": [
            "https://api-web.nhle.com/v1/score/2026-11-17"
        ],
    }
    misses = [{
        "gameId": "2026020335", "player": "Sam Reinhart",
        "earliestGate": None, "originalLockReceiptCount": 36
    }]
    recipient = {
        "status": "SOURCE_VERIFICATION_PENDING",
        "error": "PBP/boxscore scorer reconciliation incomplete",
        "notACertifiedRecipientComparison": True,
    }
    patch = {"activated": [], "decisions": []}

    _publish_official_grade(
        tmp_path, date, grade, misses, patch, recipient
    )

    saved = json.loads(card_path.read_text(encoding="utf-8"))
    audit = json.loads(saved["auditJson"])
    assert saved["cardId"] == card_id
    assert saved["fingerprint"] == "immutable-fingerprint"
    assert saved["revision"] == 3
    assert json.loads(saved["legsJson"]) == legs
    assert saved["status"] == "FROZEN_GRADED"
    assert audit["cardId"] == card_id
    assert audit["originalFingerprint"] == "immutable-fingerprint"
    assert audit["originalRevision"] == 3
    assert audit["missAudits"] == misses
    assert audit["postgameRecipientAudit"] == recipient
    assert audit["patchAdjudication"] == patch
    assert audit["status"] == "SOURCE_VERIFICATION_PENDING"
    assert audit["readOnly"] is True
    assert audit["noRetrospectiveScorerOverride"] is True
