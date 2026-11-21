"""Time-validated, ID-matched projected deployment from public NHL lineup pages.

Edgehalla explicitly builds a NEXT-GAME projection from prior official NHL
shift charts, removes out players and labels fill-ins. This is acceptable only
as PROJECTED evidence. It can NEVER establish confirmed dress/EV/PP units.

There is no inferred player identity: each listed name AND shirt number must
resolve uniquely to the same player's official current NHL team roster.
Missing/ambiguous metadata stays unverified, never a synthetic assignment.
"""
from __future__ import annotations

import asyncio
import re
import json
from datetime import date as Date, datetime, timezone
from zoneinfo import ZoneInfo
from html import unescape
from urllib.parse import quote
import httpx
from bs4 import BeautifulSoup, Tag

from .enrichment import ingest
from .lineup_parser import norm
from .secondary_sources import TEAM_SLUGS

SOURCE_BASE = "https://www.edgehalla.com/nhl/line-combinations/"
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def source_asof(html, slate_date, next_game_evidence=None):
    """Require an explicitly dated projection applicable to THIS game.

    Do not reuse yesterday's cached webpage merely because it was fetched
    today. Last-game input may be several days old, but the next-game projection
    itself must be dated for the requested day, or officially reconciled as
    the same NEXT game with no intervening completed game since the update.
    """
    soup = BeautifulSoup(html, "html.parser")
    # The page has an extensive navigation menu before the actual article.
    # Anchor the freshness check on the team's H1, never the first N body
    # characters (which contain no roster update timestamp).
    heading = next((h for h in soup.find_all("h1")
                    if "Line Combinations" in h.get_text(" ", strip=True)), None)
    if heading is None:
        return None
    all_text = soup.get_text(" ", strip=True)
    title = heading.get_text(" ", strip=True)
    at = all_text.find(title)
    if at < 0:
        return None
    sample = all_text[at:at + 1250]
    match = re.search(r"\bUpdated\s+([A-Za-z]{3,9})\s+(\d{1,2}),\s*"
                      r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET\b", sample, re.I)
    if not match:
        return None
    month = MONTHS.get(match.group(1)[:3].lower())
    if month is None:
        return None
    requested = Date.fromisoformat(slate_date)
    if "Projected for the next game" not in sample:
        return None
    year=requested.year-(month>requested.month)
    try:
        updated=Date(year,month,int(match.group(2)))
    except ValueError:
        return None
    future_match=False
    if updated!=requested:
        proof=next_game_evidence or {}
        # A dated NEXT-GAME projection may be published before game day.
        # Official schedule identity and no intervening completed game must
        # establish that it still targets THIS game, not yesterday's lineup.
        future_match=bool(updated<requested and
            updated<=datetime.now(ZoneInfo('America/New_York')).date() and
            str(proof.get('nextGameId') or '')==str(proof.get('targetGameId') or '') and
            bool(proof.get('targetGameId')) and proof.get('observedAt') and
            str(proof.get('lastFinalDate') or '')<updated.isoformat() and
            bool(proof.get('lastFinalDate')) and
            str(proof.get('sourceUrl') or '').startswith(
                'https://api-web.nhle.com/v1/club-schedule-season/'))
        if not future_match:
            return None
    return {"sourceUpdateDay": updated.isoformat(),
            "sourceUpdateTimeET": match.group(0),
            "sourceDescribesNextGameProjection": True,
            "officialNextGameIdentityVerified":future_match,
            "nextGameEvidence":next_game_evidence if future_match else None}


def roster_identity(name, jersey, roster):
    """Join surname + jersey to ONE official skater on ONE official team."""
    requested = norm(name)
    if not requested or not jersey:
        return None
    matches = []
    for player in roster:
        if str(player.get("jersey") or "") != jersey:
            continue
        official = norm(player.get("name", ""))
        if official and (official == requested or official.endswith(requested)):
            matches.append(player)
    return matches[0] if len(matches) == 1 else None


def parsed_assignments(html, roster):
    """Extract exact displayed forward lines, defensive pairs, and PP units.

    Sections are bounded by their actual h3/h4 headings, not plain string
    proximity; narrative mentions of L1/PP1 never become player deployments.
    """
    soup = BeautifulSoup(html, "html.parser")
    assignments = {}
    section = None
    current = None
    members = {}
    for node in soup.descendants:
        if not isinstance(node, Tag):
            continue
        if node.name == "h3":
            heading = node.get_text(" ", strip=True).lower()
            if "forward lines" in heading:
                section = "F"
            elif "defense pairs" in heading:
                section = "D"
            elif "power play" in heading or "power-play" in heading:
                section = "PP"
            else:
                section = None
            current = None
        elif node.name == "h4":
            raw = node.get_text(" ", strip=True).upper()
            valid = (
                (section == "F" and re.fullmatch(r"L[1-4][AB]?", raw)) or
                (section == "D" and re.fullmatch(r"D[1-3]", raw)) or
                (section == "PP" and re.fullmatch(r"PP[12]", raw))
            )
            current = (section, raw) if valid else None
            if valid:
                members[current] = {}
        elif node.name == "li" and current:
            # One player appears twice in some source widgets (summary and
            # detail), so deduplicate by independently matched official ID.
            # Jerseys and links belong to the same individual list entry.
            if node.find_parent("li") is not None:
                continue
            raw = node.get_text(" ", strip=True)
            match = re.match(r"^\s*(\d{1,2})\s+", raw)
            if not match:
                continue
            jersey = match.group(1)
            if not any(p.get("jersey") is not None and
                       str(p["jersey"]) == jersey for p in roster):
                continue
            for link in node.find_all("a", href=True):
                name = link.get_text(" ", strip=True)
                player = roster_identity(name, jersey, roster)
                if player:
                    members[current][str(player["id"])] = player
                    break
    for (kind, unit), players in members.items():
        expected = 3 if kind == "F" else 2 if kind == "D" else 5
        # Refuse half-parsed lines: the source must show a complete unit.
        if len(players) != expected:
            continue
        for pid in players:
            result = assignments.setdefault(pid, {})
            if kind in ("F", "D"):
                role = kind + unit[1]
                if "EV" in result and result["EV"] != role:
                    result["conflict"] = True
                else:
                    result["EV"] = role
            else:
                result["PP"] = int(unit[-1])
    return {pid: a for pid, a in assignments.items()
            if not a.get("conflict") and a.get("EV")}


async def collect_edgehalla_deployment(con, snapshot, slate_date, stage):
    """Source-only G6 research; no source-to-confirmation promotion."""
    if stage not in ("PROJECTED", "CONFIRMED"):
        return {"status": "NOT_PREGAME_STAGE", "deploymentRecords": 0}
    teams = sorted({t for g in snapshot.get("games", [])
                    for t in (g["away"], g["home"])})
    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0",
                                          "Accept": "text/html"}) as client:
        async def one(team):
            slug = TEAM_SLUGS.get(team)
            if not slug:
                return team, None, None, "UNKNOWN_TEAM"
            url = SOURCE_BASE + quote(slug)
            async with sem:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    return team, url, response.text, None
                except (httpx.HTTPError, ValueError) as exc:
                    return team, url, None, f"{type(exc).__name__}: {exc}"[:180]
        raw = await asyncio.gather(*(one(team) for team in teams))
    responses = {team: (url, html, error) for team, url, html, error in raw}
    observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = 0
    diagnostics = []
    for game in snapshot.get("games", []):
        for team in (game["away"], game["home"]):
            url, html, error = responses[team]
            if error or not html:
                diagnostics.append({"gameId":str(game["id"]), "team":team,
                                    "status":"SOURCE_UNAVAILABLE", "reason":error})
                continue
            context=con.execute('SELECT payload,observed_at FROM evidence '
                'WHERE slate_date=? AND stage=? AND game_id=? AND kind=? '
                'ORDER BY observed_at DESC,rowid DESC LIMIT 1',
                (slate_date,stage,str(game['id']),'MATCH_CONTEXT')).fetchone()
            facts=json.loads(context['payload']) if context else {}
            schedule_urls=[u for u in facts.get('sources',[]) if isinstance(u,str)
                and u.startswith('https://api-web.nhle.com/v1/club-schedule-season/'+team+'/')]
            prior_key='awayLastGameDate' if team==game['away'] else 'homeLastGameDate'
            next_game_proof={
                'targetGameId':str(game['id']),
                'nextGameId':(facts.get('nextScheduledGameIds') or {}).get(team),
                'lastFinalDate':facts.get(prior_key),
                'sourceUrl':schedule_urls[0] if schedule_urls else None,
                'observedAt':context['observed_at'] if context else None}
            freshness = source_asof(html, slate_date,next_game_proof)
            if not freshness:
                diagnostics.append({"gameId":str(game["id"]), "team":team,
                                    "status":"SOURCE_NOT_UPDATED_FOR_SLATE",
                                    "url":url})
                continue
            wrapper = (game.get("rosters") or {}).get(team) or {}
            roster = wrapper.get("data", {}).get("players") or []
            assignments = parsed_assignments(html, roster)
            for pid, values in assignments.items():
                ingest(con, {
                    "evidence_id": f"edgehalla-{slate_date}-{stage}-{game['id']}-{pid}",
                    "slate_date": slate_date, "stage": stage,
                    "game_id": str(game["id"]), "player_id": pid,
                    "kind": "PLAYER_DEPLOYMENT", "source_url": url,
                    "observed_at": observed,
                    "payload": {**values, "status": "PROJECTED",
                                "sourceType": "EDGEHALLA_NEXT_GAME_PROJECTION",
                                "sourceGameState": "PRIOR_FINAL_SHIFT_BASED",
                                "projectionUpdate": freshness,
                                "confirmedLineOrPP": False}
                })
                inserted += 1
            diagnostics.append({"gameId":str(game["id"]), "team":team,
                                "status":"DATED_PROJECTION_PARSED" if assignments
                                         else "DATED_PROJECTION_NO_UNAMBIGUOUS_UNITS",
                                "source":url,"playerIdsMatched":len(assignments)})
    return {"status":"G6_PROJECTED_RESEARCH_COMPLETE",
            "deploymentRecords":inserted,
            "neverConfirmed":True,"teams":diagnostics}

