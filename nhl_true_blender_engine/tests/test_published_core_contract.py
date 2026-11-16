"""Regression: a green scheduled Blender job MUST show actual 36-gate proof.

Synthetic publication fixtures. This does not override, grade or re-pick any
real NHL scorer. In production the validator reads original immutable state.
"""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.verify_published_core import (
    MASTER, OVERLAY, ORDER, verify_published_core,
)

DATE = "2026-11-16"
PUCK = "2026-11-17T00:30:00Z"
SOURCE = "https://api-web.nhle.com/v1/gamecenter/2026020331/play-by-play"


def fixture(root):
    pairs = [("2026020331", "1001", "TRANSFER"),
             ("2026020332", "1002", "PRIMARY")]
    saved = [
        {"gameId": game, "playerId": player, "player": "Synthetic " + player,
         "path": path}
        for game, player, path in pairs
    ]
    exports = []
    for game, player, path in pairs:
        receipts = []
        for i, gate in enumerate(ORDER):
            ev = ({"independentOverlayEvaluation": True,
                   "checkedBeforeG18": True,
                   "masterGateVerdictCopied": False}
                  if gate in OVERLAY else {"observed": True})
            if gate == "G18":
                ev = {
                    "overlayPassedBeforeG18": True,
                    "pathClassificationEvidence": {
                        "path": path, "selectionIndependentOfLabel": True,
                        "pathQuotaApplied": False},
                }
            receipts.append({
                "gate": gate, "status": "PASS", "evidence": ev,
                "prePuckRecord": True, "executionOrderVerified": True,
                "recordedExecutionIndex": i, "expectedExecutionIndex": i,
                "evaluatedAt": "2026-11-16T16:00:00-05:00",
                "sourceIds": [] if gate in ("G8", "G13") else [SOURCE],
            })
        exports.append({
            "gameId": game, "playerId": player, "player": "Synthetic " + player,
            "originalLockedPath": path, "startUTC": PUCK,
            "executionOrderVerified": True, "totalMaster": 20,
            "masterPassed": 20, "totalOverlay": 16, "overlayPassed": 16,
            "sourceVerifiedPregameGateCount": 36,
            "gateDetails": receipts,
        })
    cert = {
        "gateSpecification": {"executionOrder": list(ORDER),
                              "masterCount": 20, "overlayCount": 16,
                              "executionCount": 36},
        "allSkatersHaveEachGateRecord": True,
        "allSkatersHaveExactExecutionOrder": True,
        "allOverlayStepsWereIndependentlyChecked": True,
        "copiedOverlayReceiptCount": 0, "executionOrderMismatches": [],
        "fullIndependentCardCertification": True,
        "gateChecksAttempted": {x: 2 for x in ORDER},
        "masterGateDispositions": {x: {"PASS": 2} for x in MASTER},
        "overlayGateDispositions": {x: {"PASS": 2} for x in OVERLAY},
        "selectedLegs": [
            {"gameId": game, "playerId": player,
             "masterAllPass": True, "overlayAllPass": True,
             "overlayIndependentlyEvaluated": True,
             "substantivelyCertified": True,
             "semanticMissingProof": [], "executionOrderGaps": []}
            for game, player, _ in pairs
        ],
    }
    run = {
        "slateDate": DATE, "stage": "PROJECTED",
        "cardId": "SYNTHETIC-CORE", "fingerprint": "fixture-evidence-fingerprint",
        "currentRunFullyCertified": True, "publishedToSite": True,
        "cardSavedByEngine": True, "errors": [], "eligibleSkaterRows": 2,
        "gateRows": 76, "gateCertification": cert,
    }
    card = {
        "slateDate": DATE, "cardId": "SYNTHETIC-CORE",
        "fingerprint": "fixture-evidence-fingerprint", "revision": 1,
        "verified": True, "status": "G18_SOURCE_VERIFIED",
        "legsJson": json.dumps(saved),
    }
    gate_data = {
        "slateDate": DATE, "cardId": "SYNTHETIC-CORE",
        "fingerprint": "fixture-evidence-fingerprint", "revision": 1,
        "stage": "PROJECTED", "readOnly": True,
        "doesNotSelectOrReplaceScorers": True,
        "games": [{"id": a}, {"id": b}] if False else [
            {"id": x[0]} for x in pairs],
        "masterOrder": list(MASTER), "overlayOrder": list(OVERLAY),
        "executionOrder": list(ORDER), "legs": exports,
    }
    for directory, payload in (("site_runs",run),("site_cards",card),
                               ("site_gates",gate_data)):
        p = root / directory
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{DATE}.json").write_text(json.dumps(payload), encoding="utf-8")
    return run, card, gate_data


def test_passes_only_when_all_36_source_verified_pre_puck_receipts_present(tmp_path):
    fixture(tmp_path)
    result=verify_published_core(tmp_path,DATE)
    assert result["status"] == "36_GATE_INDEPENDENT_CORE_VERIFIED"
    assert result["cardId"] == "SYNTHETIC-CORE"
    assert [x["checks"] for x in result["selected"]] == [36,36]


@pytest.mark.parametrize("mutate", [
    lambda run,card,g: g["legs"][0]["gateDetails"].pop(11),
    lambda run,card,g: g["legs"][0]["gateDetails"][11].update({"status":"NOT_EXECUTED"}),
    lambda run,card,g: g["legs"][1]["gateDetails"][12].update({"sourceIds":[]}),
    lambda run,card,g: g["legs"][0]["gateDetails"][19]["evidence"].update(
        {"masterGateVerdictCopied":True}),
    lambda run,card,g: g["legs"][0]["gateDetails"][35].update(
        {"evaluatedAt":"2026-11-17T02:00:00Z"}),
    lambda run,card,g: g.update({"fingerprint":"different Core"}),
    lambda run,card,g: g["legs"][0]["gateDetails"][35]["evidence"][
        "pathClassificationEvidence"].update({"pathQuotaApplied":True}),
    lambda run,card,g: run["gateCertification"]["gateChecksAttempted"].update({"G0":1}),
])
def test_rejects_any_shortcut_or_relabelled_or_missing_gate(tmp_path,mutate):
    run,card,gates=fixture(tmp_path)
    mutate(run,card,gates)
    for directory,payload in (("site_runs",run),("site_cards",card),
                              ("site_gates",gates)):
        (tmp_path/directory/f"{DATE}.json").write_text(json.dumps(payload))
    with pytest.raises(AssertionError,match="BLENDER CORE CONTRACT FAILED"):
        verify_published_core(tmp_path,DATE)
