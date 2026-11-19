"""Ingest official NHL pre-puck *game* roster spots as dressed-status evidence.

An ordinary current roster or projected line is never a confirmed lineup.
A future game's official PBP rosterSpots may establish actual registered game
players ONLY if both complete teams are present and the document is observed
before puck drop. It does NOT establish EV lines or PP assignments (G6).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .enrichment import ingest


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:
        return None


def certified_dressed_ids(game, response):
    """Return proven team->player IDs, or (None, reason); never infer missing slots."""
    start = _instant(game.get("startUTC") or game.get("startTimeUTC"))
    observed = _instant(response.get("observedAt"))
    if not start or not observed or observed >= start:
        return None, "NOT_OBSERVED_BEFORE_PUCK"
    payload = response.get("data") or {}
    gid = str(game.get("id") or "")
    if not gid or str(payload.get("id")) != gid:
        return None, "OFFICIAL_GAME_ID_MISMATCH"
    if (game.get("gameState") not in ("FUT", "PRE")
            or payload.get("gameState") not in ("FUT", "PRE")):
        return None, "GAME_ALREADY_STARTED_OR_UNVERIFIED_STATE"
    allowed_urls = {f"https://api-web.nhle.com/v1/gamecenter/{gid}/{endpoint}"
                    for endpoint in ("play-by-play", "landing", "boxscore")}
    if response.get("url") not in allowed_urls:
        return None, "NOT_OFFICIAL_GAMECENTER_SOURCE"
    spots = payload.get("rosterSpots")
    if not isinstance(spots, list) or not spots:
        return None, "PREPUCK_GAME_ROSTER_NOT_PUBLISHED"
    spot_ids = [str(p.get("playerId")) for p in spots if isinstance(p, dict)
                and p.get("playerId") is not None]
    if len(spot_ids) != len(spots) or len(spot_ids) != len(set(spot_ids)):
        return None, "INCOMPLETE_OR_DUPLICATED_OFFICIAL_ROSTER_SPOTS"
    teams = {}
    roster_catalog = {}
    for team in (game.get("away"), game.get("home")):
        wrapper = (game.get("rosters") or {}).get(team) or {}
        roster = wrapper.get("data") or {}
        players = {str(p["id"]) for p in roster.get("players", [])
                   if isinstance(p, dict) and p.get("id") is not None}
        goalies = {str(p["id"]) for p in roster.get("goalies", [])
                   if isinstance(p, dict) and p.get("id") is not None}
        if not players or not goalies or players & goalies:
            return None, "OFFICIAL_TEAM_ROSTER_UNAVAILABLE"
        if any(pid in roster_catalog for pid in players | goalies):
            return None, "OFFICIAL_TEAM_ROSTER_IDENTITY_COLLISION"
        for pid in players:
            roster_catalog[pid] = (team, "SKATER")
        for pid in goalies:
            roster_catalog[pid] = (team, "GOALIE")
        teams[team] = {"players": set(), "goalies": set()}
    # Unrecognized roster spots can represent late official transactions. Do
    # not silently map them to a different team or call a partial slate final.
    if set(spot_ids) - set(roster_catalog):
        return None, "UNRECONCILED_OFFICIAL_GAME_ROSTER_IDENTITIES"
    for pid in spot_ids:
        team, kind = roster_catalog[pid]
        teams[team]["players" if kind == "SKATER" else "goalies"].add(pid)
    if any(len(v["players"]) < 15 or len(v["goalies"]) < 1 for v in teams.values()):
        return None, "OFFICIAL_GAME_ROSTER_NOT_COMPLETE_FOR_BOTH_TEAMS"
    return {team: sorted(v["players"]) for team, v in teams.items()}, "OFFICIAL_PREPUCK_DRESSED_ROSTER_VERIFIED"


async def collect_official_dressed(client, con, snapshot, date, stage):
    """Run before G2 and G6; collect only game-specific actual roster receipts."""
    if stage != "CONFIRMED":
        return {"status": "NOT_CONFIRMED_STAGE", "dressedPlayerReceipts": 0}
    saved = 0
    diagnostics = []
    for game in snapshot.get("games", []):
        now = datetime.now(timezone.utc)
        start = _instant(game.get("startUTC") or game.get("startTimeUTC"))
        if not start or now >= start or game.get("gameState") not in ("FUT", "PRE"):
            diagnostics.append({"gameId": game.get("id"), "status": "ALREADY_STARTED_OR_MISSING_START"})
            continue
        # Gamecenter may publish the pre-puck registered roster in its
        # landing/boxscore payload before the play-by-play rosterSpots appear.
        # Check all three exact official same-game sources without claiming
        # a dressed player from a team depth chart or a projected lineup.
        response = None
        teams = None
        attempts = []
        for endpoint in ("play-by-play", "landing", "boxscore"):
            try:
                if endpoint == "play-by-play":
                    candidate = await client.play_by_play(str(game["id"]))
                elif endpoint == "landing":
                    candidate = await client.get(f"gamecenter/{game['id']}/landing")
                else:
                    candidate = await client.boxscore(str(game["id"]))
                verified, status = certified_dressed_ids(game, candidate)
                attempts.append({"endpoint": endpoint, "status": status})
                if verified:
                    response, teams = candidate, verified
                    break
            except Exception as exc:
                attempts.append({"endpoint": endpoint, "status": "SOURCE_UNAVAILABLE",
                                 "reason": f"{type(exc).__name__}: {exc}"[:180]})
        diagnostics.append({"gameId": game["id"],
                            "status": ("OFFICIAL_PREPUCK_DRESSED_ROSTER_VERIFIED"
                                       if teams else "ALL_OFFICIAL_PREPUCK_ROSTER_SOURCES_INCOMPLETE"),
                            "sourceAttempts": attempts,
                            "dressedPlayerCount": sum(map(len, teams.values())) if teams else 0})
        if not teams:
            continue
        # The NHL source may publish a game roster before game start, but it
        # never proves an even-strength line or a power-play unit. The stricter
        # G6 deployment check remains independent.
        for team, pids in teams.items():
            for pid in pids:
                ingest(con, {
                    "evidence_id": f"official-prepuck-dressed-{date}-{game['id']}-{pid}-"
                                   + hashlib.sha256(response["observedAt"].encode()).hexdigest()[:14],
                    "slate_date": date, "stage": stage, "game_id": str(game["id"]),
                    "player_id": pid, "kind": "PLAYER_STATUS",
                    "source_url": response["url"], "observed_at": response["observedAt"],
                    "payload": {"status": "DRESSED", "team": team,
                                "sourceType": "OFFICIAL_NHL_PREPUCK_GAME_ROSTER_SPOTS",
                                "officialGameId": str(game["id"]),
                                "notEVOrPPConfirmation": True}
                })
                saved += 1
    return {"status": "OFFICIAL_PREPUCK_DRESSED_RESEARCH",
            "dressedPlayerReceipts": saved, "games": diagnostics,
            "genericCurrentRosterCannotConfirmDressed": True,
            "gameRosterSpotsNeverConfirmEVOrPP": True}
