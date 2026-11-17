"""The revoked November 17 card cannot block a fresh source-certified G16 Core.

These are synthetic receipts. No live scorer is selected or forced by tests.
"""
import json
from datetime import datetime, timedelta, timezone

from nhl_true_blender_engine.engine import MASTER, build_verified_replacement
from nhl_true_blender_engine.storage import (
    get_card, open_db, record_evidence, save_card,
)


DATE = "2026-11-17"
SOURCE = "https://api-web.nhle.com/v1/gamecenter/2026020340/play-by-play"


def leg(game, player):
    return {
        "gameId": str(game), "playerId": str(player),
        "player": "Fixture " + str(player),
        "path": "PRIMARY", "sourceIds": [SOURCE],
        "startUTC": "2099-11-18T00:00:00Z", "gameState": "FUT",
    }


def make_db(tmp_path, with_archive=True, old_status="NOT_EXECUTED"):
    con = open_db(str(tmp_path / "core.sqlite"))
    old_legs = [leg(101, 1), leg(102, 2), leg(103, 3)]
    existing = save_card(con, DATE, "PROJECTED", old_legs, 11,
                         now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
    if with_archive:
        con.execute("""CREATE TABLE card_retractions (
            slate_date TEXT PRIMARY KEY, card_id TEXT NOT NULL,
            original_fingerprint TEXT NOT NULL,
            retraction_reason TEXT NOT NULL, original_card TEXT NOT NULL,
            original_versions TEXT NOT NULL, upstream_survivors TEXT NOT NULL,
            retracted_at_utc TEXT NOT NULL)""")
        old_issued = (
            datetime.fromisoformat(existing["first_issued_at"]) -
            timedelta(hours=1)
        ).isoformat()
        con.execute(
            "INSERT INTO card_retractions VALUES (?,?,?,?,?,?,?,?)",
            (DATE, existing["card_id"], existing["fingerprint"],
             "USER_RETRACTED_INVALID_G18",
             json.dumps({"fingerprint": existing["fingerprint"],
                         "first_issued_at": old_issued}),
             "[]", "[]", datetime.now(timezone.utc).isoformat()))
    con.execute(
        "INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)",
        (DATE, "PROJECTED", "102", "2", "G10.5", old_status,
         json.dumps({"evidence": {"reason": "source not verified"},
                     "sourceIds": [SOURCE]}),
         datetime.now(timezone.utc).isoformat()))
    for game, player, kind, ev_id in [
        ("102", "2", "SKATER_SHOT_ORIGIN", "old-proof"),
        ("104", "4", "SKATER_SHOT_ORIGIN", "new-release"),
        ("104", "4", "G17_CONTRADICTION", "new-contradiction")]:
        record_evidence(con, {
            "evidence_id": ev_id, "slate_date": DATE, "stage": "PROJECTED",
            "game_id": game, "player_id": player, "kind": kind,
            "source_url": SOURCE, "observed_at": "2026-11-17T16:00:00Z",
            "payload": {"sourceReceipted": True, "player": player}})
    return con, existing


def selected(legs, contradict_id="new-contradiction"):
    result = []
    for x in legs:
        player = {
            "id": x["playerId"], "name": x["player"],
            "release": {"evidenceId": "new-release"},
            "contradictions": {"evidenceId": contradict_id},
        }
        result.append({
            "game": {"id": x["gameId"]},
            "candidate": {
                "player": player, "complete": True,
                "dispositions": {
                    gate: {"disposition": "PASS", "details": {"sourceIds": [SOURCE]}}
                    for gate in MASTER},
                "challengers": [{"status": "DEFEATED",
                                 "challengerId": "999",
                                 "sourceUrls": [SOURCE]}],
            },
        })
    return result


def test_authorized_retraction_allows_only_fresh_gate_verified_cross_game_reselection(tmp_path):
    con, existing = make_db(tmp_path)
    try:
        proposed = [leg(101, 1), leg(104, 4), leg(103, 3)]
        audit = build_verified_replacement(
            con, existing, proposed, selected(proposed), DATE, "PROJECTED")
        assert audit is not None
        assert audit["exceptionScope"] == "NOV17_PREVIOUSLY_RETRACTED_FINGERPRINT_ONLY"
        assert audit["priorSurvivorFailure"]["disposition"] == "NOT_EXECUTED"
        assert audit["priorSurvivorFailure"]["notAnEliminationWhenMissing"]
        assert audit["notAManualSelection"] is True
        replacement = save_card(con, DATE, "PROJECTED", proposed, 11, audit=audit)
        assert replacement["revision"] == 2
        assert replacement["current_legs"] == proposed
        assert replacement["initial_legs"] == existing["initial_legs"]
        version = con.execute(
            "SELECT rationale FROM card_versions WHERE slate_date=? AND revision=2",
            (DATE,)).fetchone()
        rationale = json.loads(version["rationale"])
        assert rationale["type"] == "GATE_VALIDATED_REPLACEMENT"
        assert rationale["audit"]["priorSurvivorFailure"]["notAnEliminationWhenMissing"]
        assert con.execute(
            "SELECT disposition FROM gates WHERE slate_date=? AND player_id='2' "
            "AND gate='G10.5'", (DATE,)).fetchone()["disposition"] == "NOT_EXECUTED"
        assert con.execute("SELECT COUNT(*) FROM card_retractions").fetchone()[0] == 1
    finally:
        con.close()


def test_no_retraction_never_allows_projected_cross_game_swap(tmp_path):
    con, existing = make_db(tmp_path, with_archive=False)
    try:
        new = [leg(101, 1), leg(104, 4), leg(103, 3)]
        assert build_verified_replacement(
            con, existing, new, selected(new), DATE, "PROJECTED") is None
        assert get_card(con, DATE)["current_legs"] == existing["current_legs"]
    finally:
        con.close()


def test_retracted_old_card_still_passes_original_gate_cannot_be_overwritten(tmp_path):
    con, existing = make_db(tmp_path, old_status="PASS")
    try:
        new = [leg(101, 1), leg(104, 4), leg(103, 3)]
        assert build_verified_replacement(
            con, existing, new, selected(new), DATE, "PROJECTED") is None
    finally:
        con.close()


def test_retraction_cannot_bypass_new_gate_failure_or_missing_g17_receipt(tmp_path):
    con, existing = make_db(tmp_path)
    try:
        new = [leg(101, 1), leg(104, 4), leg(103, 3)]
        wrong = selected(new)
        wrong[1]["candidate"]["dispositions"]["G17"]["disposition"] = "NOT_EXECUTED"
        assert build_verified_replacement(
            con, existing, new, wrong, DATE, "PROJECTED") is None
        assert build_verified_replacement(
            con, existing, new, selected(new, contradict_id="made-up-id"),
            DATE, "PROJECTED") is None
    finally:
        con.close()
