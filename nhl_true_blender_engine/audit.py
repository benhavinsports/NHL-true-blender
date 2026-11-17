"""Immutable-lock-scoped miss audit.

A later CONFIRMED source gap, a post-puck rerun, or a missed goal cannot
retroactively turn a previously certified PROJECTED Core into a failed gate.
Audit the exact saved card stage at its issuance timestamp. Search archived
gate-history receipts when subsequent diagnostics have replaced live rows.
"""
from __future__ import annotations

import json
from datetime import datetime

from .storage import stamp, transaction, encode, get_card
from .engine import GATE_PATCHES, MASTER, OVERLAY

REQUIRED = tuple(MASTER + OVERLAY)
GATE_INDEX = {gate: index for index, gate in enumerate(MASTER[:-1] + OVERLAY + [MASTER[-1]])}


def configure_audit_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS miss_audits (
        slate_date TEXT NOT NULL, game_id TEXT NOT NULL, player_id TEXT NOT NULL,
        card_id TEXT NOT NULL, conclusion TEXT NOT NULL, earliest_gate TEXT,
        patch_ids TEXT NOT NULL, source_comparison TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(slate_date,game_id,player_id)
    )""")


def _timestamp(value):
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return out if out.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _issued_gate_receipts(con, date, card, leg):
    """Read only receipts from the stage/clock of this exact saved revision.

    The current gates table is replaceable diagnostics. gate_history stores
    prior snapshots and can recover the original G18-issued pass matrix.
    Neither a later stage nor a later timestamp can override that selection.
    """
    stage = card.get("stage")
    issued = _timestamp(card.get("updated_at") or card.get("first_issued_at"))
    puck = _timestamp(leg.get("startUTC"))
    if stage not in ("PROJECTED", "CONFIRMED") or issued is None or puck is None:
        return {}, {"status": "ORIGINAL_LOCK_TIMESTAMP_UNAVAILABLE", "stage": stage}
    cutoff = min(issued, puck)
    game_id, pid = str(leg["gameId"]), str(leg["playerId"])
    query = """SELECT gate,disposition,details,evaluated_at FROM {table}
               WHERE slate_date=? AND stage=? AND game_id=? AND player_id=?"""
    receipts = {}
    archived_count = 0
    for table in ("gate_history", "gates"):
        for row in con.execute(query.format(table=table), (date, stage, game_id, pid)):
            measured = _timestamp(row["evaluated_at"])
            if measured is None or measured > cutoff or row["gate"] not in GATE_INDEX:
                continue
            prior = receipts.get(row["gate"])
            if prior is None or measured > prior[0]:
                receipts[row["gate"]] = (measured, row)
            if table == "gate_history":
                archived_count += 1
    return {gate: item[1] for gate, item in receipts.items()}, {
        "status": "ISSUANCE_ANCHORED_GATE_RECEIPTS",
        "stage": stage, "issuedAt": issued.isoformat(), "puckDrop": puck.isoformat(),
        "archivedPregameRowsConsidered": archived_count,
        "crossStageRowsNeverOverrideOriginalCard": True,
        "postIssuanceRowsExcluded": True,
    }


def audit_misses(con, date):
    configure_audit_table(con)
    card = get_card(con, date)
    if not card or not card["grade"]:
        return []
    grade = con.execute("SELECT legs FROM grades WHERE card_id=?", (card["card_id"],)).fetchone()
    if not grade:
        return []
    original = {(str(leg["gameId"]), str(leg["playerId"])): leg
                for leg in card["current_legs"]}
    result = []
    for outcome in json.loads(grade["legs"]):
        if outcome["result"] == "HIT":
            continue
        game_id, pid = str(outcome["gameId"]), str(outcome["playerId"])
        selected = original.get((game_id, pid))
        if selected is None:
            raise ValueError("Cannot audit goal miss for a player outside original locked Core")
        rows, scope = _issued_gate_receipts(con, date, card, selected)
        absent = sorted(set(REQUIRED) - set(rows), key=lambda gate: GATE_INDEX[gate])
        failures = sorted((gate for gate, row in rows.items()
                           if row["disposition"] != "PASS"), key=lambda gate: GATE_INDEX[gate])
        earliest = sorted(set(absent + failures), key=lambda gate: GATE_INDEX[gate])
        earliest = earliest[0] if earliest else None
        # Missing historical receipts are audit gaps, not proof the player
        # failed the original scoring path. Nor do they justify patching it.
        conclusion = ("ORIGINAL_LOCK_GATE_RECEIPTS_UNVERIFIED" if earliest else
                      "MISS_WITHOUT_PROVEN_PREGAME_GATE_DEFECT")
        patches = []  # Outcome or missing records alone cannot activate a patch.
        detail = {
            **scope,
            "preGameGateRows": len(rows),
            "expectedGateRows": len(REQUIRED),
            "missingOriginalGateRows": absent,
            "nonpassingOriginalGateRows": failures,
            "firstUnverifiedGate": earliest,
            "officialGoalCount": int(outcome["goals"]),
            "provenPatchApplication": False,
            "futurePatchRequiresIndependentPregameSourceContradiction": True,
        }
        existing = con.execute("""SELECT conclusion,earliest_gate FROM miss_audits
                    WHERE slate_date=? AND game_id=? AND player_id=?""",
                    (date, game_id, pid)).fetchone()
        if existing and (existing["conclusion"] != conclusion
                         or existing["earliest_gate"] != earliest):
            detail["previousCrossPhaseAuditCorrected"] = {
                "conclusion": existing["conclusion"], "earliestGate": existing["earliest_gate"]}
        with transaction(con):
            con.execute("""INSERT INTO miss_audits
                (slate_date,game_id,player_id,card_id,conclusion,earliest_gate,
                 patch_ids,source_comparison,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(slate_date,game_id,player_id) DO UPDATE SET
                  conclusion=excluded.conclusion,earliest_gate=excluded.earliest_gate,
                  patch_ids=excluded.patch_ids,source_comparison=excluded.source_comparison,
                  created_at=excluded.created_at""",
                (date, game_id, pid, card["card_id"], conclusion, earliest,
                 encode(patches), encode(detail), stamp()))
        result.append({
            "player": outcome["player"], "gameId": game_id,
            "earliestGate": earliest, "patchesToAudit": patches,
            "conclusion": conclusion, "auditStage": scope["stage"],
            "originalLockReceiptCount": len(rows),
        })
    return result
