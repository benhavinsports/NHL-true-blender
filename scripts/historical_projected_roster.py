"""Recover a game-scoped *projected* team skater pool from dated official NHL previews.

This is a pre-slate source-verified player-membership pool, NOT an official
confirmed dressed roster, the season's complete transaction roster, or a new
selection rule.  Every included name was independently matched to an NHL
season-roster ID by the upstream NHL.com article collector, and the archived
article was published / last modified before the replay cutoff.

To avoid silently omitting depth/defense rivals from a decision, only a full
four-forward-line + three-defense-pair projection can become a G2 player pool.
Partial articles stay as individual PLAYER_DEPLOYMENT evidence and are NOT
silently promoted to complete skater pools.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json

SOURCE = "OFFICIAL_NHL_COM_PROJECTED_LINEUP_ARTICLE"


def _utc(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (TypeError, ValueError):
        return None


def recover_full_projected_team_pool(rows, *, date, game_id, team, cutoff):
    """Return immutable replay-only roster receipt or None, never fake depth."""
    expected = {
        (f"L{line}", role)
        for line in range(1, 5) for role in ("LW", "C", "RW")
    } | {(f"D{pair}", "D") for pair in range(1, 4)}
    # Defense-pair roles occur twice. Enforce six actual distinct defense IDs
    # rather than deduplicating a pair into one "D" position.
    per_source = defaultdict(list)
    for row in rows:
        if row["kind"] != "PLAYER_DEPLOYMENT":
            continue
        if str(row["game_id"]) != str(game_id) or row["stage"] != "PROJECTED":
            continue
        payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        if (payload.get("sourceType") != SOURCE or
                payload.get("team") != team or
                payload.get("officialSeasonRosterIdentityMatched") is not True or
                payload.get("status") != "PROJECTED"):
            continue
        published = _utc(payload.get("sourceArticlePublishedAt"))
        modified = _utc(payload.get("sourceArticleModifiedAt")) if payload.get("sourceArticleModifiedAt") else None
        captured = _utc(row["observed_at"])
        if (not published or published > cutoff or not captured or captured > cutoff
                or (modified and modified > cutoff)):
            continue
        if (not row["player_id"] or
                payload.get("EVRole") not in ("LW", "C", "RW", "D") or
                not isinstance(payload.get("playerName"), str) or
                not payload.get("playerName", "").strip()):
            continue
        per_source[row["source_url"]].append((row, payload, published, modified))

    eligible = []
    for url, entries in per_source.items():
        # Exact 4x3 forward roles and 3x2 defensive pairs on one source page.
        roles = [(x[1]["EV"], x[1]["EVRole"]) for x in entries]
        counts = {role: roles.count(role) for role in set(roles)}
        required_counts = {
            **{(f"L{line}", role): 1 for line in range(1, 5)
               for role in ("LW", "C", "RW")},
            **{(f"D{pair}", "D"): 2 for pair in range(1, 4)}
        }
        ids = [str(x[0]["player_id"]) for x in entries]
        if counts != required_counts or len(ids) != 18 or len(set(ids)) != 18:
            continue
        # A single archived article revision must be coherent: mixing
        # old/new versions of an article would invent a pregame lineup.
        clocks = {(published, modified) for _, _, published, modified in entries}
        if len(clocks) != 1:
            continue
        published, modified = next(iter(clocks))
        players = [
            {"id": str(r["player_id"]), "name": payload["playerName"].strip(),
             "position": "D" if payload["EVRole"] == "D" else payload["EVRole"],
             "availability": "UNVERIFIED", "projectedEV": payload["EV"]}
            for r, payload, _, _ in entries
        ]
        players.sort(key=lambda x: x["id"])
        receipt_ids = sorted(str(r["evidence_id"]) for r, _, _, _ in entries)
        payload = {
            "team": team, "players": players, "goalies": [],
            "sourceType": "OFFICIAL_NHL_DATED_PROJECTED_GAME_SKATER_POOL",
            "projectionSourceType": SOURCE,
            "scope": "ALL_FOUR_PROJECTED_FORWARD_LINES_AND_THREE_DEFENSE_PAIRS",
            "fullProjectedSkaterLineupObserved": True,
            "completeOrganizationalCurrentRosterNotClaimed": True,
            "notConfirmedDressedOrEVUnits": True,
            "independentOfficialSeasonRosterIdMatches": 18,
            "sourceArticlePublishedAt": published.isoformat(),
            "sourceArticleModifiedAt": modified.isoformat() if modified else None,
            "sourceEvidenceIds": receipt_ids,
            "historicalReconstruction": True,
            "historicalSourceObservedAtCutoffVerified": False,
            "noPostgameRosterSpotsUsed": True
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
        eligible.append({
            "evidence_id": f"replay-full-projected-team-{date}-{game_id}-{team}-{digest}",
            "slate_date": date,
            # OFFICIAL here denotes the NHL.com publisher, never a confirmed
            # line status. The *payload* always remains PROJECTED.
            "stage": "OFFICIAL", "game_id": str(game_id), "player_id": None,
            "kind": "TEAM_CURRENT_ROSTER",
            "source_url": url, "observed_at": published.isoformat(),
            "payload": json.dumps(payload, sort_keys=True)
        })
    # Conflicting complete articles cannot be arbitrarily resolved.
    return eligible[0] if len(eligible) == 1 else None
