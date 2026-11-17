"""Rebuild only read-only published gate receipts from the existing ledger.

This is a deployment export, NEVER a scorer selection or evidence mutation.
An incomplete new review cannot displace better pre-puck evidence tied to the
same authoritative card. Past card fingerprints remain immutable.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from nhl_true_blender_engine.dashboard_export import export_dashboard
from nhl_true_blender_engine.storage import open_db


def full_pass_count(payload):
    return sum(
        leg.get("masterPassed") == leg.get("totalMaster") == 20
        and leg.get("overlayPassed") == leg.get("totalOverlay") == 16
        and leg.get("executionOrderVerified") is True
        for leg in payload.get("legs", [])
    )


def evidence_strength(payload):
    """Count actual pre-puck PASSes; never regress a displayed source receipt."""
    return (
        full_pass_count(payload),
        sum(int(leg.get("masterPassed") or 0) +
            int(leg.get("overlayPassed") or 0)
            for leg in payload.get("legs", []))
    )


def archived_receipt_diagnostics(con, date, legs):
    """Summary of archived cohorts only; never manufacture a gate PASS."""
    from collections import defaultdict
    from datetime import datetime
    result = []
    for leg in legs:
        puck = datetime.fromisoformat(leg["startUTC"].replace("Z", "+00:00"))
        rows = con.execute("""
            SELECT stage,gate,disposition,evaluated_at
            FROM gate_history
            WHERE slate_date=? AND game_id=? AND player_id=?""",
            (date, str(leg["gameId"]), str(leg["playerId"]))).fetchall()
        groups = defaultdict(list)
        for row in rows:
            groups[(row["stage"], row["evaluated_at"])].append(row)
        cohorts = []
        for (stage, timestamp), batch in groups.items():
            at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            unique_gates = {row["gate"] for row in batch}
            cohorts.append({
                "stage": stage, "evaluatedAt": timestamp,
                "beforePuck": at < puck,
                "gateCount": len(unique_gates),
                "passCount": sum(row["disposition"] == "PASS" for row in batch),
                "missingOrNonpassing": 36 - sum(
                    row["disposition"] == "PASS" for row in batch)
            })
        cohorts.sort(key=lambda x: (x["passCount"], x["gateCount"]), reverse=True)
        result.append({
            "playerId": str(leg["playerId"]),
            "gameId": str(leg["gameId"]),
            "archivedRows": len(rows),
            "archivedCohorts": len(cohorts),
            "bestPrePuckCohorts": [x for x in cohorts
                if x["beforePuck"]][:3],
            "bestPostPuckCohorts": [x for x in cohorts
                if not x["beforePuck"]][:1],
        })
    return result


def recover_committed_original(root, date, saved, candidate):
    """Restore the immutable original saved pre-puck receipt, never inferred PASSes.

    An older coherent PROJECTED G18 source receipt may have been overwritten
    by the later CONFIRMED diagnostic export. The original file is a byte-copy
    of a verified Git commit and must match the unchanged authoritative Core.
    """
    from datetime import datetime
    from nhl_true_blender_engine.engine import EXECUTION_ORDER

    original_path = root / "site_gates" / (date + "-original-projected.json")
    if not original_path.is_file():
        return candidate
    original = json.loads(original_path.read_text(encoding="utf-8"))
    if (original.get("cardId") != saved.get("cardId")
            or original.get("fingerprint") != saved.get("fingerprint")
            or original.get("stage") != "PROJECTED"
            or original.get("readOnly") is not True
            or original.get("doesNotSelectOrReplaceScorers") is not True):
        return candidate
    frozen = json.loads(saved.get("legsJson", "[]"))
    expected = {(str(x["gameId"]), str(x["playerId"])) for x in frozen}
    recovered = {(str(x["gameId"]), str(x["playerId"]))
                 for x in original.get("legs", [])}
    current = {(str(x["gameId"]), str(x["playerId"]))
               for x in candidate.get("legs", [])}
    if not expected or recovered != expected or current != expected:
        return candidate
    if original.get("revision") != saved.get("revision"):
        return candidate
    # Verify the exact source-backed, ordered, individually timestamped
    # pre-puck trace. Never count a checklist or reconstructed gate label.
    required_anchors = {"G0", "G6", "G10.5", "G17", "G18"}
    for leg in original["legs"]:
        trace = leg.get("gateDetails") or []
        if (leg.get("masterPassed") != 20 or leg.get("overlayPassed") != 16
                or leg.get("executionOrderVerified") is not True
                or len(trace) != len(EXECUTION_ORDER)):
            return candidate
        try:
            puck = datetime.fromisoformat(leg["startUTC"].replace("Z","+00:00"))
            for index, record in enumerate(trace):
                when = datetime.fromisoformat(
                    record["evaluatedAt"].replace("Z","+00:00"))
                if (record.get("gate") != EXECUTION_ORDER[index]
                        or record.get("status") != "PASS"
                        or record.get("prePuckRecord") is not True
                        or record.get("recordedExecutionIndex") != index
                        or record.get("expectedExecutionIndex") != index
                        or record.get("executionOrderVerified") is not True
                        or when >= puck):
                    return candidate
                if record["gate"] in required_anchors and not any(
                        isinstance(u,str) and u.startswith("https://")
                        for u in record.get("sourceIds", [])):
                    return candidate
        except (TypeError, KeyError, ValueError):
            return candidate
    if full_pass_count(candidate) == len(candidate["legs"]):
        return candidate
    latest = {(str(leg["gameId"]),str(leg["playerId"])):leg
              for leg in candidate["legs"]}
    for leg in original["legs"]:
        key = (str(leg["gameId"]),str(leg["playerId"]))
        review = latest[key].get("separatePhaseReviews") or {}
        leg["latestReviewStage"] = candidate.get("stage", "CONFIRMED")
        leg["sourceGateArchive"] = True
        leg["separatePhaseReviews"] = {
            **review,
            "PROJECTED": {
                "available": True, "recoveredArchivedOriginal": True,
                "fullOriginalOrderPass": True, "prePuckGateRows": 36,
                "masterPassed": 20, "overlayPassed": 16,
                "nonpassingGates": {}
            }
        }
    original["stage"] = candidate.get("stage", "CONFIRMED")
    original["savedOriginalStage"] = "PROJECTED"
    original["originalSourceCommit"] = "3c0b3126544"
    original["games"] = candidate.get("games") or original.get("games", [])
    original["deploymentRefreshIsReadOnly"] = True
    return original


def refresh(root="state"):
    root = Path(root)
    db = root / "true_blender.sqlite"
    if not db.exists():
        return {"status": "NO_STORED_LEDGER", "updated": []}
    con = open_db(str(db))
    updated = []
    preserved = []
    incomplete_archive_audits = []
    try:
        for path in sorted((root / "site_gates").glob("????-??-??.json")):
            date = path.stem
            card_path = root / "site_cards" / (date + ".json")
            if not card_path.exists():
                continue
            saved = json.loads(card_path.read_text(encoding="utf-8"))
            if saved.get("verified") is not True:
                continue
            previous = json.loads(path.read_text(encoding="utf-8"))
            if (previous.get("cardId") != saved.get("cardId")
                    or previous.get("fingerprint") != saved.get("fingerprint")):
                preserved.append({"date": date, "reason": "CARD_IDENTITY_MISMATCH"})
                continue
            # Recover the original full-slate summary verbatim; the DB
            # pre-puck player/goalie receipts provide the gate proofs.
            # Never replace actual games with fabricated empty matchups.
            with TemporaryDirectory() as scratch:
                export_dashboard(con, date, "CONFIRMED", {"games": []}, scratch)
                candidate_path = Path(scratch) / "site_gates" / (date + ".json")
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            if (candidate.get("cardId") != previous["cardId"]
                    or candidate.get("fingerprint") != previous["fingerprint"]
                    or {(str(x["gameId"]), str(x["playerId"]))
                        for x in candidate.get("legs", [])}
                    != {(str(x["gameId"]), str(x["playerId"]))
                        for x in previous.get("legs", [])}):
                preserved.append({"date": date, "reason": "RECIPIENT_IDENTITY_MISMATCH"})
                continue
            candidate = recover_committed_original(root, date, saved, candidate)
            if full_pass_count(candidate) < len(candidate.get("legs", [])):
                incomplete_archive_audits.append({
                    "date": date, "cohortEvidence": archived_receipt_diagnostics(
                        con, date, json.loads(saved.get("legsJson", "[]")))})
            if evidence_strength(candidate) < evidence_strength(previous):
                preserved.append({"date": date, "reason": "PREVIOUS_PREPUCK_RECEIPTS_STRONGER",
                                  "prior": evidence_strength(previous),
                                  "reconstructed": evidence_strength(candidate)})
                continue
            candidate["games"] = previous.get("games", [])
            candidate["deploymentRefreshIsReadOnly"] = True
            candidate["doesNotSelectOrReplaceScorers"] = True
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(candidate, sort_keys=True, indent=2, default=str)+"\n",
                            encoding="utf-8")
            temp.replace(path)
            latest_leg=candidate["legs"][0] if candidate.get("legs") else {}
            cursor=con.execute("""
                SELECT stage, COUNT(*) AS total, MIN(evaluated_at) AS first,
                    MAX(evaluated_at) AS last
                FROM gates WHERE slate_date=? AND game_id=? AND player_id=?
                GROUP BY stage""", (date,latest_leg.get("gameId"),
                                    latest_leg.get("playerId"))).fetchall()
            past=con.execute("""
                SELECT stage, COUNT(*) AS total, MIN(evaluated_at) AS first,
                    MAX(evaluated_at) AS last
                FROM gate_history WHERE slate_date=? AND game_id=? AND player_id=?
                GROUP BY stage""", (date,latest_leg.get("gameId"),
                                    latest_leg.get("playerId"))).fetchall()
            updated.append({"date": date,
                            "fullyCertifiedLegs": full_pass_count(candidate),
                            "legs": len(candidate["legs"]),
                            "sourcePhases": [x["stageOfGateRecords"]
                                for x in candidate["legs"]],
                            "reviews": latest_leg.get("separatePhaseReviews"),
                            "activeRaw": [dict(row) for row in cursor],
                            "archivedRaw": [dict(row) for row in past]})
    finally:
        con.close()
    return {"status": "READ_ONLY_EXPORT", "updated": updated,
            "preserved": preserved,
            "incompleteArchiveAudits": incomplete_archive_audits}


if __name__ == "__main__":
    print(json.dumps(refresh(), sort_keys=True))
