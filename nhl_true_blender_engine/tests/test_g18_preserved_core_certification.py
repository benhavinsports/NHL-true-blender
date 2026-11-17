"""A frozen legacy card cannot certify a new G18 run with extra survivors.

The fixtures here are artificial player IDs. This test never selects or
relabels a real scorer; it checks the published state of an engine failure.
"""
import json

from nhl_true_blender_engine.engine import MASTER, OVERLAY
from scripts.publish_site_state import export_run


DATE = "2026-11-17"


def _result(extra=True):
    recipients = [
        {"gameId": "101", "playerId": "11"},
        {"gameId": "102", "playerId": "22"},
        {"gameId": "103", "playerId": "33"},
    ]
    survivors = recipients + ([{"gameId": "104", "playerId": "44"}] if extra else [])
    count = len(survivors)
    return {
        "card": None, "games": count,
        "errors": ([f"PRE_CORE_REVIEW: {count} qualified; G18 cannot rank"]
                   if extra else []),
        "allG18QualifiedSurvivors": survivors,
        "gateCertification": {
            "scannedSkaters": count,
            "gateChecksAttempted": {gate: count for gate in MASTER + OVERLAY},
            "allSkatersHaveEachGateRecord": True,
            "allSkatersHaveExactExecutionOrder": True,
            "allOverlayStepsWereIndependentlyChecked": True,
            "copiedOverlayReceiptCount": 0,
            "twoDirectionsPerScheduledGameRecorded": True,
            "selectedCoreOnlyFullyCertified": True,
        },
    }


def test_frozen_three_cannot_verify_new_four_survivor_run(tmp_path):
    original = [
        {"gameId": "101", "playerId": "11"},
        {"gameId": "102", "playerId": "22"},
        {"gameId": "103", "playerId": "33"},
    ]
    folder = tmp_path / "site_cards"
    folder.mkdir()
    card = {"cardId": "ORIGINAL-CORE", "legsJson": json.dumps(original),
            "verified": True}
    (folder / (DATE + ".json")).write_text(json.dumps(card))
    result = export_run(None, DATE, "PROJECTED", _result(), root=tmp_path)
    assert result["currentRunFullyCertified"] is False
    assert result["publishedToSite"] is False
    assert result["retainedOriginalLockedCard"] is True
    assert result["publicationDecision"] == "G18_UPSTREAM_SURVIVORS_UNRESOLVED"
    assert result["qualifiedSurvivorCount"] == 4
    assert result["historicalLockedLegCount"] == 3
    assert json.loads((folder / (DATE + ".json")).read_text()) == card


def test_preserving_a_matching_card_does_not_generate_new_recipients(tmp_path):
    original = [
        {"gameId": "101", "playerId": "11"},
        {"gameId": "102", "playerId": "22"},
        {"gameId": "103", "playerId": "33"},
    ]
    folder = tmp_path / "site_cards"
    folder.mkdir()
    (folder / (DATE + ".json")).write_text(json.dumps({
        "cardId": "ORIGINAL-CORE", "legsJson": json.dumps(original),
        "verified": True,
    }))
    result = export_run(None, DATE, "PROJECTED", _result(extra=False),
                        root=tmp_path)
    assert result["publicationDecision"] == "PRESERVED_FROZEN_CORE_NO_NEW_SELECTION"
    assert result["currentRunFullyCertified"] is True
    assert result["publishedToSite"] is True
