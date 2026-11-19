"""Replay-only G2 membership reconstruction: source proof, full units, no time travel."""
import json
from datetime import datetime, timezone

from nhl_true_blender_engine.storage import open_db, record_evidence
from scripts.historical_projected_roster import recover_full_projected_team_pool
from scripts.build_replay_bundles import build_day


DAY = "2026-10-02"
GAME = "2026020030"
URL = "https://www.nhl.com/news/boston-bruins-new-york-rangers-game-preview-october-2-2026"
CUTOFF = datetime(2026, 10, 2, 22, 55, tzinfo=timezone.utc)


def source_rows(*, late=False, short=False, wrong_team=False):
    roles = [(f"L{line}", side) for line in range(1, 5)
             for side in ("LW", "C", "RW")]
    roles += [(f"D{pair}", "D") for pair in range(1, 4) for _ in range(2)]
    if short:
        roles.pop()
    published = "2026-10-02T23:10:00Z" if late else "2026-10-02T17:00:00Z"
    return [{
        "evidence_id": f"verified-pre-slate-article-{i}",
        "slate_date": DAY, "stage": "PROJECTED", "game_id": GAME,
        "player_id": str(8400000 + i),
        "kind": "PLAYER_DEPLOYMENT", "source_url": URL,
        "observed_at": published,
        "payload": json.dumps({
            "team": "NYR" if wrong_team and i == 1 else "BOS",
            "playerName": f"Source Verified Player {i}",
            "EV": unit, "EVRole": role, "status": "PROJECTED",
            "sourceType": "OFFICIAL_NHL_COM_PROJECTED_LINEUP_ARTICLE",
            "officialSeasonRosterIdentityMatched": True,
            "sourceArticlePublishedAt": published,
            "sourceArticleModifiedAt": published,
            "historicalReconstruction": True,
            "projectedNotConfirmed": True,
        }),
    } for i, (unit, role) in enumerate(roles)]


def test_complete_pre_cutoff_projected_full_skater_pool_is_source_scoped():
    full = recover_full_projected_team_pool(
        source_rows(), date=DAY, game_id=GAME, team="BOS", cutoff=CUTOFF)
    assert full is not None
    payload = json.loads(full["payload"])
    assert len(payload["players"]) == 18
    assert sum(x["position"] == "D" for x in payload["players"]) == 6
    assert payload["sourceType"] == "OFFICIAL_NHL_DATED_PROJECTED_GAME_SKATER_POOL"
    assert payload["completeOrganizationalCurrentRosterNotClaimed"] is True
    assert payload["notConfirmedDressedOrEVUnits"] is True
    assert full["source_url"] == URL


def test_partial_or_future_or_cross_team_membership_never_creates_complete_pool():
    for rows in (source_rows(short=True), source_rows(late=True),
                 source_rows(wrong_team=True)):
        assert recover_full_projected_team_pool(
            rows, date=DAY, game_id=GAME, team="BOS", cutoff=CUTOFF) is None


def test_complete_eleven_seven_pool_preserves_all_independently_identified_skaters():
    rows = source_rows()
    for row in rows:
        payload = json.loads(row["payload"])
        payload["officialPosition"] = "D" if payload["EVRole"] == "D" else "C"
        if payload["EV"] == "L4":
            if payload["EVRole"] == "RW":
                payload.update(EV="D4", EVRole="D", officialPosition="D")
            else:
                payload["EVRole"] = "F"
        row["payload"] = json.dumps(payload)
    full = recover_full_projected_team_pool(rows, date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF)
    assert full is not None
    data = json.loads(full["payload"])
    assert len(data["players"]) == 18
    assert sum(p["position"] == "D" for p in data["players"]) == 7
    assert {p["id"] for p in data["players"]} == {r["player_id"] for r in rows}
    assert all(p["position"] != "F" for p in data["players"])
    # A short roster or an unverified role cannot be promoted to a full pool.
    assert recover_full_projected_team_pool(rows[:-1], date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is None
    payload = json.loads(rows[-1]["payload"])
    payload.pop("officialPosition")
    rows[-1]["payload"] = json.dumps(payload)
    assert recover_full_projected_team_pool(rows, date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is None


def test_repeated_identical_receipts_are_not_extra_roster_spots():
    rows = source_rows()
    repeated = [{**r, "evidence_id": r["evidence_id"] + "-repeat"} for r in rows]
    assert recover_full_projected_team_pool(rows + repeated, date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is not None
    conflicting = dict(repeated[0])
    payload = json.loads(conflicting["payload"])
    payload["EV"] = "L2"
    conflicting["payload"] = json.dumps(payload)
    assert recover_full_projected_team_pool(rows + [conflicting], date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is None


def test_new_parser_never_fills_missing_spots_from_legacy_or_conflicting_article_bytes():
    legacy = source_rows()
    current = []
    for row in legacy:
        payload = json.loads(row["payload"])
        payload.update(sourceParserVersion=2, sourceArticleSha256="source-one")
        current.append({**row, "evidence_id": row["evidence_id"] + "-new", "payload": json.dumps(payload)})
    assert recover_full_projected_team_pool(legacy + current, date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is not None
    assert recover_full_projected_team_pool(legacy + current[:-1], date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is None
    payload = json.loads(current[-1]["payload"])
    payload["sourceArticleSha256"] = "different-source-bytes"
    current[-1]["payload"] = json.dumps(payload)
    assert recover_full_projected_team_pool(current, date=DAY, game_id=GAME,
                                           team="BOS", cutoff=CUTOFF) is None


def test_reconstructed_pool_reaches_bundle_only_when_archived_roster_missing(tmp_path):
    db = open_db(str(tmp_path / "source.sqlite"))
    try:
        for item in source_rows():
            record_evidence(db, {**item, "payload": json.loads(item["payload"])})
        bundle = build_day(db, DAY, tmp_path / "out", {
            "source": "https://api-web.nhle.com/v1/score/2026-10-02",
            "downloadedAt": "2026-11-19T00:00:00Z",
            "games": [{
                "id": GAME, "away": "BOS", "home": "NYR",
                "startTimeUTC": "2026-10-02T23:00:00Z",
            }]
        })
        snapshot = json.loads((tmp_path / "out" / bundle["snapshot"]).read_text())
        roster = snapshot["games"][0]["rosters"]["BOS"]
        assert roster["data"]["fullProjectedSkaterLineupObserved"] is True
        assert len(roster["data"]["players"]) == 18
        assert snapshot["games"][0]["rosters"]["NYR"] is None
        assert bundle["stage"] == "PROJECTED"
        assert bundle["teamsWithSourceVerifiedFullProjectedSkaterPool"] == ["BOS"]
        assert bundle["teamsMissingHistoricalRoster"] == ["BOS", "NYR"]
    finally:
        db.close()


def test_reconstructed_pool_does_not_override_real_archived_official_roster(tmp_path):
    db = open_db(str(tmp_path / "source.sqlite"))
    try:
        for item in source_rows():
            record_evidence(db, {**item, "payload": json.loads(item["payload"])})
        record_evidence(db, {
            "evidence_id": "independently-saved-official-roster",
            "slate_date": DAY, "stage": "OFFICIAL",
            "kind": "TEAM_CURRENT_ROSTER",
            "source_url": "https://api-web.nhle.com/v1/roster/BOS/current",
            "observed_at": "2026-10-02T16:00:00Z",
            "payload": {"team": "BOS", "players": [
                {"id": "991", "name": "Saved Official Member", "position": "C"}],
                "goalies": [], "sourceType": "OFFICIAL_CURRENT_ROSTER_NOT_DRESSED"},
        })
        bundle = build_day(db, DAY, tmp_path / "out", {
            "source": "https://api-web.nhle.com/v1/score/2026-10-02",
            "games": [{
                "id": GAME, "away": "BOS", "home": "NYR",
                "startTimeUTC": "2026-10-02T23:00:00Z",
            }],
        })
        snapshot = json.loads((tmp_path / "out" / bundle["snapshot"]).read_text())
        assert [p["id"] for p in snapshot["games"][0]["rosters"]["BOS"]["data"]["players"]] == ["991"]
        assert bundle["teamsWithSourceVerifiedFullProjectedSkaterPool"] == []
    finally:
        db.close()
