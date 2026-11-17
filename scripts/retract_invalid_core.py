"""One-slate, identity-checked retraction of a card produced by invalid G18 rules.

A retraction is NOT a player replacement, score adjustment, or arbitrary
selection. It removes the discredited card from the active ledger while
preserving the original immutable identity, every previous version, and all
original source/gate rows. Only a later, full corrected engine pass can issue
a new active card. It is scoped to the user-authorized November 17 repair.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from nhl_true_blender_engine.storage import open_db, transaction

DATE = "2026-11-17"
ORIGINAL_FINGERPRINT = "3b3862e259b6acedaed43de619a759b27f64ec9ffc02459be32c938f86e278d6"
CARD_ID = "NHL-2026-11-17-CANONICAL"
REASON = "PREVIOUS_G18_UNAUTHORIZED_RANKING_SELECTED_THREE_OF_FOUR_UPSTREAM_SURVIVORS"


def retract(root="state", now=None):
    root = Path(root)
    manifest_path = root / "core_retractions" / (DATE + ".json")
    public_path = root / "site_cards" / (DATE + ".json")
    if not manifest_path.is_file():
        return {"status": "NO_RETRACTION_MANIFEST"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("slateDate") != DATE
            or manifest.get("originalFingerprint") != ORIGINAL_FINGERPRINT
            or manifest.get("cardId") != CARD_ID
            or manifest.get("reason") != REASON
            or manifest.get("approval") != "USER_EXPLICITLY_REJECTED_OLD_G18_CARD"
            or len(manifest.get("upstreamSurvivors", [])) != 4
            or len({(str(x["gameId"]),str(x["playerId"]))
                    for x in manifest["upstreamSurvivors"]}) != 4):
        raise ValueError("Retraction manifest identity/evidence mismatch")
    # This is a one-time migration. Once the exact old card and versions
    # have been archived, later live slates MUST NOT revalidate the original
    # four-survivor snapshot against fresh, changed player evidence.
    db_path = root / "true_blender.sqlite"
    checkpoint = open_db(str(db_path))
    try:
        checkpoint.execute("""CREATE TABLE IF NOT EXISTS card_retractions (
            slate_date TEXT PRIMARY KEY, card_id TEXT NOT NULL,
            original_fingerprint TEXT NOT NULL,
            retraction_reason TEXT NOT NULL,
            original_card TEXT NOT NULL, original_versions TEXT NOT NULL,
            upstream_survivors TEXT NOT NULL,
            retracted_at_utc TEXT NOT NULL
        )""")
        archived = checkpoint.execute(
            "SELECT * FROM card_retractions WHERE slate_date=?", (DATE,)
        ).fetchone()
        active = checkpoint.execute(
            "SELECT * FROM cards WHERE slate_date=?", (DATE,)
        ).fetchone()
        if archived:
            if (archived["card_id"] != CARD_ID
                    or archived["original_fingerprint"] != ORIGINAL_FINGERPRINT):
                raise ValueError("Existing retraction archive identity mismatch")
            if active:
                # The REAL corrected selection may independently produce the
                # same three names/fingerprint. A fingerprint alone cannot
                # make a newly issued post-retraction card "the old one".
                issued=datetime.fromisoformat(
                    active["first_issued_at"].replace("Z","+00:00"))
                old_issued=datetime.fromisoformat(
                    json.loads(archived["original_card"])["first_issued_at"]
                    .replace("Z","+00:00"))
                # Both database/card timestamps are second-resolution, and
                # an honest reissue can happen in the SAME SECOND as its
                # invalidation. Compare against the preserved ORIGINAL
                # first-issued time, not the second-level retraction clock.
                if issued<=old_issued:
                    raise ValueError("Retracted original returned to active canonical cards")
                versions=checkpoint.execute("""SELECT COUNT(*) FROM card_versions
                    WHERE slate_date=?""",(DATE,)).fetchone()[0]
                if not versions:
                    raise ValueError("New corrected card lacks its own source-issued version")
                return {"status":"NEW_CORRECTED_CARD_EXISTS",
                        "originalCardId":CARD_ID,
                        "identicalPlayersMayBeIndependentlyReissued":True}
            return {"status":"ORIGINAL_ALREADY_RETRACTED",
                    "originalCardId":CARD_ID}
    finally:
        checkpoint.close()
    run_path = root / "site_runs" / (DATE + ".json")
    source_run = json.loads(run_path.read_text(encoding="utf-8"))
    observed = source_run.get("preCoreQualifiedSurvivors") or []
    actual_ids = {(str(x["gameId"]), str(x["playerId"])) for x in observed}
    manifest_ids = {(str(x["gameId"]), str(x["playerId"]))
                    for x in manifest["upstreamSurvivors"]}
    if (len(observed) != 4 or actual_ids != manifest_ids
            or source_run.get("slateDate") != DATE
            or not any("PRE_CORE_REVIEW:" in str(x)
                       for x in source_run.get("errors", []))):
        raise ValueError("Refuse retraction without same-slate four-survivor proof")
    published = json.loads(public_path.read_text(encoding="utf-8"))
    if (published.get("cardId") != CARD_ID
            or published.get("fingerprint") != ORIGINAL_FINGERPRINT
            or published.get("verified") is not False
            or published.get("status") != "RETRACTED_UNAUTHORIZED_G18"):
        # A later corrected, independently issued verified card must be
        # preserved, never retracted by this one-shot historical manifest.
        if published.get("verified") is True and (root / "core_retractions" / (DATE + ".json")).exists():
            # Once the original has been archived, a subsequent card can
            # independently earn the same exact recipients under new rules.
            check = open_db(str(root / "true_blender.sqlite"))
            try:
                row = check.execute(
                    "SELECT 1 FROM card_retractions WHERE slate_date=?", (DATE,)
                ).fetchone()
            except Exception:
                row = None
            finally:
                check.close()
            if row:
                return {"status": "NEW_CORRECTED_CARD_EXISTS"}
        raise ValueError("Retraction requires matching explicit JSON tombstone")
    con = open_db(str(root / "true_blender.sqlite"))
    try:
        with transaction(con):
            con.execute("""CREATE TABLE IF NOT EXISTS card_retractions (
                slate_date TEXT PRIMARY KEY, card_id TEXT NOT NULL,
                original_fingerprint TEXT NOT NULL,
                retraction_reason TEXT NOT NULL,
                original_card TEXT NOT NULL, original_versions TEXT NOT NULL,
                upstream_survivors TEXT NOT NULL,
                retracted_at_utc TEXT NOT NULL
            )""")
            already = con.execute(
                "SELECT * FROM card_retractions WHERE slate_date=?", (DATE,)
            ).fetchone()
            active = con.execute("SELECT * FROM cards WHERE slate_date=?", (DATE,)).fetchone()
            if active:
                if (active["card_id"] != CARD_ID
                        or active["fingerprint"] != ORIGINAL_FINGERPRINT
                        or active["grade"] is not None):
                    raise ValueError("Active card identity changed or has been officially graded")
                # No fake backdated replacement or post-puck new selection.
                # The stored card is invalidated now; all old/source rows stay.
                versions = [dict(v) for v in con.execute(
                    "SELECT * FROM card_versions WHERE slate_date=? ORDER BY revision", (DATE,)
                ).fetchall()]
                if already:
                    raise ValueError("Retracted original appeared in active cards a second time")
                con.execute("""INSERT INTO card_retractions VALUES (?,?,?,?,?,?,?,?)""",(
                    DATE,CARD_ID,ORIGINAL_FINGERPRINT,REASON,
                    json.dumps(dict(active),sort_keys=True),
                    json.dumps(versions,sort_keys=True),
                    json.dumps(manifest["upstreamSurvivors"],sort_keys=True),
                    datetime.now(timezone.utc).isoformat(timespec="seconds")
                ))
                con.execute("DELETE FROM cards WHERE slate_date=?", (DATE,))
                con.execute("DELETE FROM card_versions WHERE slate_date=?", (DATE,))
                return {"status":"ORIGINAL_RETRACTED_FROM_ACTIVE_LEDGER",
                        "originalVersionsPreserved":len(versions),
                        "originalCardId":CARD_ID,
                        "skaterGateEvidenceUnaffected":True,
                        "replacementMustBeSelectedByCorrectedEngine":True}
            if not already:
                raise ValueError("Original active card absent without preserved retraction receipt")
            return {"status":"ORIGINAL_ALREADY_RETRACTED",
                    "originalCardId":CARD_ID}
    finally:
        con.close()


if __name__ == "__main__":
    print(json.dumps(retract(), sort_keys=True))
