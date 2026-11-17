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


def refresh(root="state"):
    root = Path(root)
    db = root / "true_blender.sqlite"
    if not db.exists():
        return {"status": "NO_STORED_LEDGER", "updated": []}
    con = open_db(str(db))
    updated = []
    preserved = []
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
            "preserved": preserved}


if __name__ == "__main__":
    print(json.dumps(refresh(), sort_keys=True))
