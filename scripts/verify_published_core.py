"""Independent acceptance check of the *published* NHL True Blender Core.

Do not trust a workflow's green check, a UI badge, or a single "certified"
boolean. Cross-check the canonical card against the saved G0-G18/overlay
receipts, their ordered indices, source provenance, and pre-puck timestamps.

This is read-only. It never selects, relabels, replaces, or grades a skater.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

MASTER = tuple([f"G{i}" for i in range(11)] + ["G10.5"] +
               [f"G{i}" for i in range(11, 19)])
OVERLAY = tuple([f"Step{i}" for i in range(11)] + ["Step10.5"] +
                [f"Step{i}" for i in range(11, 15)])
STEP_OWNER = {"Step0":"G0","Step1":"G2","Step2":"G3","Step3":"G5",
              "Step4":"G4","Step5":"G7","Step6":"G6","Step7":"G9",
              "Step8":"G8","Step9":"G9","Step10":"G10",
              "Step10.5":"G10.5","Step11":"G11","Step12":"G16",
              "Step13":"G13","Step14":"G17"}
ORDER = tuple(item for gate in MASTER
              for item in (gate,)+tuple(step for step in OVERLAY
                                         if STEP_OWNER[step]==gate))
SOURCE_OPTIONAL_NONELIMINATION = frozenset(("G8", "G13"))


def _require(ok, message):
    if not ok:
        raise AssertionError("BLENDER CORE CONTRACT FAILED: " + message)


def _read(root: Path, date: str, subdir: str):
    path = root / subdir / (date + ".json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssertionError(
            "BLENDER CORE CONTRACT FAILED: unreadable " + str(path) + ": " + str(exc)
        ) from exc


def verify_published_core(root: Path, date: str):
    """Validate a *real saved* run, not a synthetic skeleton or checklist."""
    run = _read(root, date, "site_runs")
    card = _read(root, date, "site_cards")
    gates = _read(root, date, "site_gates")
    _require(run.get("slateDate") == card.get("slateDate") ==
             gates.get("slateDate") == date, "slate date disagreement")
    _require(run.get("stage") in ("PROJECTED", "CONFIRMED"), "invalid run phase")
    _require(gates.get("stage") == run["stage"], "gate receipts from different phase")
    _require(run.get("currentRunFullyCertified") is True and
             run.get("publishedToSite") is True and
             run.get("cardSavedByEngine") is True and
             not run.get("errors"), "run not fully certified and saved")
    _require(card.get("verified") is True and
             card.get("status") == "G18_SOURCE_VERIFIED",
             "unverified or incomplete canonical card")
    _require(gates.get("readOnly") is True and
             gates.get("doesNotSelectOrReplaceScorers") is True,
             "site data might be performing scorer selection")
    _require(run.get("cardId") == card.get("cardId") == gates.get("cardId"),
             "multiple competing Core card identities")
    _require(run.get("fingerprint") == card.get("fingerprint") ==
             gates.get("fingerprint"), "canonical saved-card fingerprint differs")
    _require(card.get("revision") == gates.get("revision"), "card revision differs")
    _require(gates.get("masterOrder") == list(MASTER) and
             gates.get("overlayOrder") == list(OVERLAY) and
             gates.get("executionOrder") == list(ORDER),
             "wrong/missing/reordered master or overlay gate specification")
    certification = run.get("gateCertification") or {}
    spec = certification.get("gateSpecification") or {}
    _require(spec.get("executionOrder") == list(ORDER) and
             spec.get("masterCount") == 20 and
             spec.get("overlayCount") == 16 and
             spec.get("executionCount") == 36,
             "runner's actual 36-gate specification does not match master rules")
    _require(certification.get("allSkatersHaveEachGateRecord") is True and
             certification.get("allSkatersHaveExactExecutionOrder") is True and
             certification.get("allOverlayStepsWereIndependentlyChecked") is True and
             certification.get("copiedOverlayReceiptCount") == 0 and
             certification.get("executionOrderMismatches") == [] and
             certification.get("fullIndependentCardCertification") is True,
             "runner did not independently evaluate every gate for every skater")
    skaters = run.get("eligibleSkaterRows")
    _require(type(skaters) is int and skaters > 0, "no evaluated skater pool")
    for gate in ORDER:
        attempted = (certification.get("gateChecksAttempted") or {}).get(gate)
        _require(attempted == skaters, f"{gate} attempted for {attempted}/{skaters} skaters")
        outcomes = ((certification.get("masterGateDispositions") or {})
                    if gate in MASTER else
                    (certification.get("overlayGateDispositions") or {})).get(gate) or {}
        _require(sum(v for v in outcomes.values() if type(v) is int) == skaters,
                 f"{gate} missing saved outcome for some skaters")
    _require(run.get("gateRows", 0) >= skaters * len(ORDER),
             "fewer actual gate rows than skaters multiplied by 36")
    games = gates.get("games") or []
    required = 2 if len(games) == 2 else 3
    _require(len(games) >= 2 and len(gates.get("legs") or []) == required,
             "incorrect Core 2/3 count for this slate")
    try:
        original = json.loads(card["legsJson"])
    except (KeyError, ValueError, TypeError) as exc:
        raise AssertionError("BLENDER CORE CONTRACT FAILED: invalid canonical legs") from exc
    selected = gates["legs"]
    _require(len(original) == len(selected) == required,
             "published Core differs from canonical saved legs")
    exact_original = {(str(x["gameId"]), str(x["playerId"])): x for x in original}
    exact_export = {(str(x["gameId"]), str(x["playerId"])): x for x in selected}
    # G18 assembles the Core; it cannot silently discard an upstream survivor.
    # Today's November 17 receipt demonstrated why selected-leg PASS counts
    # alone are insufficient: four qualified, three published.
    survivors = run.get("allG18QualifiedSurvivors")
    _require(isinstance(survivors, list),
             "saved run omitted the full upstream survivor set")
    survivor_ids = [(str(x.get("gameId")), str(x.get("playerId")))
                    for x in survivors]
    _require(len(survivor_ids) == required and
             len(set(survivor_ids)) == required and
             set(survivor_ids) == set(exact_original),
             "G18 silently dropped, added, or duplicated fully qualified survivors")
    _require(len(exact_original) == len(exact_export) == required and
             set(exact_original) == set(exact_export),
             "duplicate/cross-game/changed selected players")
    _require(len({x["gameId"] for x in original}) == required,
             "two Core skaters selected from the same NHL game")
    certified_legs = {
        (str(x["gameId"]), str(x["playerId"])): x
        for x in certification.get("selectedLegs", [])
    }
    _require(set(certified_legs) == set(exact_export),
             "gate certification audited different legs than the published Core")
    for identity, leg in exact_export.items():
        who = str(leg.get("player") or identity)
        published = exact_original[identity]
        _require(leg.get("originalLockedPath") == published.get("path"),
                 who + " published label differs from original locked card")
        _require(leg.get("executionOrderVerified") is True,
                 who + " did not independently verify gate execution order")
        _require(leg.get("masterPassed") == 20 and
                 leg.get("overlayPassed") == 16 and
                 leg.get("sourceVerifiedPregameGateCount") == 36 and
                 leg.get("totalMaster") == 20 and
                 leg.get("totalOverlay") == 16,
                 who + " did not pass all 20 master and 16 independent overlay checks")
        trace = leg.get("gateDetails") or []
        _require([x.get("gate") for x in trace] == list(ORDER),
                 who + " missing, duplicated, or reordered gate receipts")
        puck = datetime.fromisoformat(str(leg["startUTC"]).replace("Z","+00:00"))
        _require(puck.tzinfo is not None, who + " puck-drop timestamp has no timezone")
        for index, row in enumerate(trace):
            gate = ORDER[index]
            _require(row.get("status") == "PASS" and
                     row.get("executionOrderVerified") is True and
                     row.get("prePuckRecord") is True and
                     row.get("recordedExecutionIndex") == index and
                     row.get("expectedExecutionIndex") == index,
                     who + " " + gate + " wasn't genuinely passed in sequence before puck drop")
            measured = datetime.fromisoformat(
                str(row.get("evaluatedAt") or "").replace("Z", "+00:00"))
            _require(measured.tzinfo is not None and measured < puck,
                     who + " " + gate + " contains post-puck or undated evidence")
            source_ids = row.get("sourceIds") or []
            _require(isinstance(source_ids, list), who + " " + gate + " malformed provenance")
            if gate not in SOURCE_OPTIONAL_NONELIMINATION:
                _require(any(isinstance(u, str) and u.startswith("https://")
                             for u in source_ids),
                         who + " " + gate + " missing source attribution")
            if gate in OVERLAY:
                ev = row.get("evidence") or {}
                _require(ev.get("independentOverlayEvaluation") is True and
                         ev.get("checkedBeforeG18") is True and
                         ev.get("masterGateVerdictCopied") is False,
                         who + " " + gate + " used a copied/master gate shortcut")
        g18 = trace[-1]["evidence"]
        path = g18.get("pathClassificationEvidence") or {}
        _require(path.get("path") == leg["originalLockedPath"] and
                 path.get("path") in ("PRIMARY", "TRANSFER", "WHO") and
                 path.get("selectionIndependentOfLabel") is True and
                 path.get("pathQuotaApplied") is False and
                 g18.get("overlayPassedBeforeG18") is True,
                 who + " G18 label not demonstrably derived after all checks")
        proof = certified_legs[identity]
        _require(proof.get("masterAllPass") is True and
                 proof.get("overlayAllPass") is True and
                 proof.get("overlayIndependentlyEvaluated") is True and
                 proof.get("substantivelyCertified") is True and
                 proof.get("semanticMissingProof") == [] and
                 proof.get("executionOrderGaps") == [],
                 who + " lacks semantic source certification")
    return {"slateDate":date,"status":"36_GATE_INDEPENDENT_CORE_VERIFIED",
            "cardId":card["cardId"],"stage":run["stage"],
            "eligibleSkaters":skaters,"gateRows":run["gateRows"],
            "selected": [{"player":x["player"],"path":x["originalLockedPath"],
                          "checks":len(x["gateDetails"])} for x in selected]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--root", default="state")
    args = parser.parse_args()
    print(json.dumps(verify_published_core(Path(args.root), args.date),indent=2))
