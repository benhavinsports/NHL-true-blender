"""Independent acceptance check of the *published* NHL True Blender Core.

Do not trust a workflow's green check, a UI badge, or a single "certified"
boolean. Cross-check the canonical card against the one original G0-G18
sequence, nested original function evidence, provenance and pre-puck times.

This is read-only. It never selects, relabels, replaces, or grades a skater.
"""
from __future__ import annotations
from nhl_true_blender_engine.core_identity import expected_core_ids
from nhl_true_blender_engine.engine import MASTER, OVERLAY, EXECUTION_ORDER, STEPS_BY_GATE
from nhl_true_blender_engine.semantic_certification import audit_gate

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

# The engine owns the authoritative gate order; never reconstruct a second
# chronology in the publication verifier.
ORDER = tuple(EXECUTION_ORDER)
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
             gates.get("originalFunctionNames") == list(OVERLAY) and
             gates.get("oneOriginalGatePipeline") is True and
             gates.get("executionOrder") == list(ORDER),
             "saved receipt is not the single original G0-G18 sequence")
    certification = run.get("gateCertification") or {}
    spec = certification.get("gateSpecification") or {}
    _require(spec.get("executionOrder") == list(ORDER) and
             spec.get("oneGatePipeline") is True and
             spec.get("masterCount") == len(MASTER) and
             spec.get("embeddedFunctionCount") == len(OVERLAY) and
             spec.get("executionCount") == len(ORDER),
             "runner's canonical G0-G18 specification does not match engine")
    _require(certification.get("allSkatersHaveEachGateRecord") is True and
             certification.get("allSkatersHaveExactExecutionOrder") is True and
             certification.get("allOriginalFunctionsWereCheckedWithinGates") is True and
             certification.get("copiedOverlayReceiptCount") == 0 and
             certification.get("executionOrderMismatches") == [] and
             certification.get("fullIndependentCardCertification") is True,
             "runner did not independently evaluate every gate for every skater")
    # G0 direction-UNRESOLVED research is executed against each actual
    # player/possible goalie branch, but it is NEVER a scorer-eligible
    # G0-selected player row. The old published contract incorrectly used
    # all 267 official IDs as the 222 G0-selected matrix denominator.
    # Preserve every research receipt, certify only the real matrix cohort.
    # Historical read-only contract fixtures predate the separate
    # research counter. They describe no G0 branch research, so their
    # total official pool equals the candidate pool.
    skaters = certification.get("scannedSkaters",
                                run.get("eligibleSkaterRows"))
    all_official = run.get("eligibleSkaterRows")
    research_official = certification.get("g0ResearchOnlyOfficialSkaters",0)
    research_branches = certification.get("g0ResearchOnlyBranchMatrices",0)
    _require(type(skaters) is int and skaters > 0,
             "no scorer-eligible executed G0 player matrices")
    _require(type(all_official) is int and type(research_official) is int
             and all_official==skaters+research_official,
             "actual official player pool was hidden or research was double-counted")
    _require(type(research_branches) is int and research_branches>=0
             and certification.get("g0ResearchOnlyGateRows",0)==research_branches*len(ORDER),
             "unresolved G0 branches lack the original gate investigation")
    for gate in ORDER:
        attempted = (certification.get("gateChecksAttempted") or {}).get(gate)
        _require(attempted == skaters, f"{gate} attempted for {attempted}/{skaters} skaters")
        outcomes = (certification.get("masterGateDispositions") or {}).get(gate) or {}
        _require(sum(v for v in outcomes.values() if type(v) is int) == skaters,
                 f"{gate} missing saved outcome for some skaters")
    # All historical source functions must be accounted for, but their
    # observations must never be counted as additional selection gates.
    for step in OVERLAY:
        # Source function observations are nested, not additional gate
        # executions; their authoritative coverage is reported separately.
        outcomes=(certification.get("originalFunctionDispositions") or {}).get(step) or {}
        checked=sum(v for v in outcomes.values() if type(v) is int)
        _require(checked==skaters,
                 f"{step} original function reviewed for {checked}/{skaters}")
    _require(run.get("gateRows", 0) >=
             (skaters+research_branches)*len(ORDER)+run.get("g0Directions",0),
             "full original G0-G18 candidate and goalie branch rows incomplete")
    games = gates.get("games") or []
    required = 2 if len(games) == 2 else 3
    # G18 is the final assembled card, not a source-pass for every provisional
    # game survivor. Earlier runs reported five G18 PASS rows but selected
    # three; that must now invalidate publication rather than look green.
    final_counts=(certification.get("masterGateDispositions") or {}).get("G18") or {}
    _require(final_counts.get("PASS") == required,
             "G18 PASS count does not equal the final Core size")
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
    # G16's saved cross-game finalist receipt (if any) defines the exact
    # survivors G18 may assemble; every other survivor needs a G16 exclusion.
    survivor_ids = expected_core_ids(run)
    _require(survivor_ids is not None,
             "saved G16 finalist competition is missing, unseparated or inconsistent")
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
        _require(leg.get("masterPassed") == len(MASTER) and
                 leg.get("originalFunctionsPassed") == len(OVERLAY) and
                 leg.get("sourceVerifiedPregameGateCount") == len(ORDER) and
                 leg.get("totalMaster") == len(MASTER),
                 who + " lacks the original G0-G18 gates or embedded functions")
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
            # A function named StepN is evidence WITHIN this gate. There
            # cannot be a second StepN gate row or an aliased PASS label.
            ev=row.get("evidence") or {}
            functions=ev.get("originalFunctionEvidence") or []
            _require([x.get("step") for x in functions]==STEPS_BY_GATE[gate],
                     who + " " + gate + " skipped/duplicated a required original function")
            for sub in functions:
                name=sub.get("step")
                info=sub.get("evidence") or {}
                status=sub.get("disposition")
                neutral=(name=="Step13" and info.get("nonblocking") is True)
                _require(status=="PASS" or neutral,
                         who + " " + gate + " source function " + str(name) +
                         " has a nonpassing result")
                _require(info.get("independentOverlayEvaluation") is True and
                         info.get("checkedBeforeG18") is True and
                         info.get("masterGateVerdictCopied") is False,
                         who + " " + gate + " source function " + str(name) +
                         " copied a gate decision")
                citations=sub.get("sourceIds") or []
                _require(isinstance(citations,list) and all(
                    isinstance(x,str) and x.startswith("https://") for x in citations),
                    who + " " + gate + " source function citations malformed")
                if status=="PASS":
                    _require(not audit_gate(name,info,citations,run["stage"]),
                             who + " " + gate + " source function " + str(name) +
                             " lacks substantive evidence")
        g18 = trace[-1]["evidence"]
        path = g18.get("pathClassificationEvidence") or {}
        _require(path.get("path") == leg["originalLockedPath"] and
                 path.get("path") in ("PRIMARY", "TRANSFER", "WHO") and
                 path.get("selectionIndependentOfLabel") is True and
                 path.get("pathQuotaApplied") is False and
                 g18.get("originalFunctionsReviewedBeforeG18") is True,
                 who + " G18 label not demonstrably derived after all checks")
        proof = certified_legs[identity]
        _require(proof.get("masterAllPass") is True and
                 proof.get("overlayAllPass") is True and
                 proof.get("overlayIndependentlyEvaluated") is True and
                 proof.get("substantivelyCertified") is True and
                 proof.get("semanticMissingProof") == [] and
                 proof.get("executionOrderGaps") == [],
                 who + " lacks semantic source certification")
    return {"slateDate":date,"status":"ORIGINAL_G0_G18_CORE_VERIFIED",
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
