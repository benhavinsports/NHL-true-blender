"""Independently verify a previously saved pre-puck Core receipt for Pages.

Do NOT call a failed new run successful, reselect recipients, or resurrect an
explicitly revoked G18 fingerprint. A new nonpassing research pass does not
erase an older source-verified, pre-puck, revisioned card and its gate details.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from nhl_true_blender_engine.engine import EXECUTION_ORDER, STEPS_BY_GATE, OVERLAY
from nhl_true_blender_engine.semantic_certification import audit_gate, nonblocking_overlay_review

OPTIONAL_SOURCE_GATES = frozenset(("G8", "G13"))


def verified_original_receipt(root, slate_date, card):
    """Return the saved matrix only when its own G0–G18 source proof is valid.

    The current run's gate decisions are intentionally NOT consulted here:
    this is proof of the card's prior independently saved source cohort.
    """
    root=Path(root)
    if (not isinstance(card, dict) or
            card.get("slateDate") != slate_date or
            card.get("verified") is not True or
            card.get("status") not in ("G18_SOURCE_VERIFIED", "FROZEN_GRADED")):
        return None
    # Never show the fingerprint explicitly withdrawn by the user merely
    # because a prior export marked it verified. A later independently valid
    # replacement has its OWN different fingerprint and source receipt.
    tombstone=root/"core_retractions"/(slate_date+".json")
    if tombstone.exists():
        try:
            revoked=json.loads(tombstone.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            return None
        if (revoked.get("slateDate")==slate_date and
                revoked.get("cardId")==card.get("cardId") and
                revoked.get("originalFingerprint")==card.get("fingerprint")):
            return None

    path=root/"site_gates"/(slate_date+".json")
    try:
        matrix=json.loads(path.read_text(encoding="utf-8"))
        legs=json.loads(card["legsJson"])
    except (OSError,ValueError,KeyError,TypeError):
        return None
    order=list(EXECUTION_ORDER)
    if (matrix.get("slateDate")!=slate_date or
        matrix.get("cardId")!=card.get("cardId") or
        matrix.get("fingerprint")!=card.get("fingerprint") or
        matrix.get("revision")!=card.get("revision") or
        matrix.get("oneOriginalGatePipeline") is not True or
        matrix.get("readOnly") is not True or
        matrix.get("doesNotSelectOrReplaceScorers") is not True or
        matrix.get("masterOrder")!=order or
        matrix.get("executionOrder")!=order or
        matrix.get("originalFunctionNames")!=list(OVERLAY) or
        matrix.get("stage") not in ("PROJECTED","CONFIRMED") or
        len(legs) not in (2,3) or
        len({str(l["gameId"]) for l in legs}) != len(legs) or
        len(matrix.get("legs") or []) != len(legs)):
        return None
    original_ids={(str(l["gameId"]),str(l["playerId"])) for l in legs}
    if len(original_ids)!=len(legs):
        return None
    matrix_by_id={(str(l.get("gameId")),str(l.get("playerId"))):l for l in matrix["legs"]}
    if set(matrix_by_id)!=original_ids:return None
    for leg in legs:
        key=(str(leg["gameId"]),str(leg["playerId"]))
        receipt=matrix_by_id[key]
        if (receipt.get("executionOrderVerified") is not True or
            receipt.get("masterPassed")!=len(order) or
            receipt.get("totalMaster")!=len(order) or
            receipt.get("overlayPassed")!=len(OVERLAY) or
            receipt.get("totalOverlay")!=len(OVERLAY) or
            receipt.get("sourceVerifiedPregameGateCount")!=len(order) or
            receipt.get("originalLockedPath")!=leg.get("path")):
            return None
        try:
            puck=datetime.fromisoformat(str(leg["startUTC"]).replace("Z","+00:00"))
        except (KeyError,ValueError,TypeError):
            return None
        rows=receipt.get("gateDetails") or []
        if [r.get("gate") for r in rows]!=order:return None
        for pos,row in enumerate(rows):
            if (row.get("status")!="PASS" or
                row.get("prePuckRecord") is not True or
                row.get("executionOrderVerified") is not True or
                row.get("recordedExecutionIndex")!=pos or
                row.get("expectedExecutionIndex")!=pos):
                return None
            try:
                observed=datetime.fromisoformat(str(row["evaluatedAt"]).replace("Z","+00:00"))
            except (KeyError,ValueError,TypeError):
                return None
            if observed>=puck:return None
            urls=row.get("sourceIds") or []
            if not isinstance(urls,list):return None
            if row["gate"] not in OPTIONAL_SOURCE_GATES and not any(
                isinstance(url,str) and url.startswith("https://") for url in urls):
                return None
            ev=row.get("evidence") or {}
            nested=ev.get("originalFunctionEvidence") or []
            if [e.get("step") for e in nested]!=STEPS_BY_GATE[row["gate"]]:
                return None
            for sub in nested:
                info=sub.get("evidence") or {}
                neutral=nonblocking_overlay_review(sub.get("step"),info,sub.get("disposition"))
                if ((sub.get("disposition")!="PASS" and not neutral) or
                    info.get("independentOverlayEvaluation") is not True or
                    info.get("checkedBeforeG18") is not True or
                    info.get("masterGateVerdictCopied") is not False):
                    return None
            # Defends against a synthetic PASS with a URL but missing the
            # original physical-route facts required by its gate.
            historical=slate_date < datetime.now(ZoneInfo('America/New_York')).date().isoformat()
            if audit_gate(row["gate"],ev,urls,matrix["stage"],
                          preserve_historical_contract=historical):
                return None
    return matrix

