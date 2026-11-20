"""Ingest verifiable pregame NHL.com projected lineup deployments (not rosters).

This source is only valid when official article publication metadata has an
offset-aware timestamp BEFORE that matchup’s pregame deadline. A date-only article
or page modified after cutoff is excluded; no postgame correction is allowed.
Official historical season rosters resolve player IDs only, never establish
a dated complete roster or a confirmed lineup.
"""
from __future__ import annotations
import argparse
import asyncio
from scripts.historical_pregame_clock import game_deadline
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import httpx
from nhl_true_blender_engine.sources import NHLClient
from nhl_true_blender_engine.enrichment import ingest
from nhl_true_blender_engine.storage import open_db

TEAMS = {
    "ANA": ("anaheim-ducks", "Ducks"), "BOS": ("boston-bruins", "Bruins"),
    "BUF": ("buffalo-sabres", "Sabres"), "CGY": ("calgary-flames", "Flames"),
    "CAR": ("carolina-hurricanes", "Hurricanes"),
    "CBJ": ("columbus-blue-jackets", "Blue Jackets"),
    "CHI": ("chicago-blackhawks", "Blackhawks"),
    "COL": ("colorado-avalanche", "Avalanche"),
    "DAL": ("dallas-stars", "Stars"), "DET": ("detroit-red-wings", "Red Wings"),
    "EDM": ("edmonton-oilers", "Oilers"), "FLA": ("florida-panthers", "Panthers"),
    "LAK": ("los-angeles-kings", "Kings"), "MIN": ("minnesota-wild", "Wild"),
    "MTL": ("montreal-canadiens", "Canadiens"),
    "NJD": ("new-jersey-devils", "Devils"),
    "NSH": ("nashville-predators", "Predators"),
    "NYI": ("new-york-islanders", "Islanders"),
    "NYR": ("new-york-rangers", "Rangers"),
    "OTT": ("ottawa-senators", "Senators"),
    "PHI": ("philadelphia-flyers", "Flyers"),
    "PIT": ("pittsburgh-penguins", "Penguins"),
    "SEA": ("seattle-kraken", "Kraken"),
    "SJS": ("san-jose-sharks", "Sharks"),
    "STL": ("st-louis-blues", "Blues"),
    "TBL": ("tampa-bay-lightning", "Lightning"),
    "TOR": ("toronto-maple-leafs", "Maple Leafs"),
    "UTA": ("utah-mammoth", "Mammoth"),
    "VAN": ("vancouver-canucks", "Canucks"),
    "VGK": ("vegas-golden-knights", "Golden Knights"),
    "WSH": ("washington-capitals", "Capitals"),
    "WPG": ("winnipeg-jets", "Jets")
}
BLOCK = {"p", "h1", "h2", "h3", "h4", "li", "article", "section", "br"}


def utc(value):
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return timestamp.astimezone(timezone.utc) if timestamp.tzinfo else None
    except (ValueError, TypeError):
        return None


class Article(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.meta = []
        self.invisible = 0
        self.script = None
        self.jsonld = []
        self._buffer = []
    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "meta":
            self.meta.append(props)
        if tag in ("style", "noscript", "script"):
            self.invisible += 1
            if tag == "script" and "ld+json" in props.get("type", ""):
                self.script = []
        if tag in BLOCK and not self.invisible:
            self._flush()
    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.jsonld.append("".join(self.script))
            self.script = None
        if tag in ("style", "noscript", "script"):
            self.invisible = max(0, self.invisible - 1)
        if tag in BLOCK and not self.invisible:
            self._flush()
    def handle_data(self, text):
        if self.script is not None:
            self.script.append(text)
        if not self.invisible and text.strip():
            self._buffer.append(text.strip())
    def _flush(self):
        if self._buffer:
            self.lines.append(" ".join(self._buffer).strip())
            self._buffer = []


def publication_clock(article):
    published, modified = [], []
    for m in article.meta:
        k = str(m.get("property") or m.get("itemprop") or m.get("name") or "").lower()
        value = m.get("content") or m.get("datetime")
        if k in ("article:published_time", "datepublished", "published_time"):
            if utc(value):
                published.append(utc(value))
        if k in ("article:modified_time", "datemodified", "modified_time"):
            if utc(value):
                modified.append(utc(value))
    for script in article.jsonld:
        for key, target in (("datePublished", published), ("dateModified", modified)):
            for value in re.findall(r'"' + key + r'"\s*:\s*"([^"]+)"', script):
                if utc(value):
                    target.append(utc(value))
    return min(published) if published else None, max(modified) if modified else None


def normalize(name):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode().lower())


def preview_url(game, date):
    away, home = (TEAMS.get(game.get(k), (None,))[0] for k in ("away", "home"))
    if not away or not home:
        return None
    month = datetime.fromisoformat(date).strftime("%B").lower()
    day = int(date[-2:])
    return f"https://www.nhl.com/news/{away}-{home}-game-preview-{month}-{day}-{date[:4]}"


def read_lines(lines, team, positions=None):
    """Return independently named projected EV assignments, no PP claim."""
    nickname = TEAMS[team][1].lower()
    matches = [i for i, line in enumerate(lines)
               if line.strip().lower().endswith("projected lineup")
               and nickname in line.strip().lower()]
    if len(matches) != 1:
        return []
    i = matches[0] + 1
    out = []
    forward, defense = 0, 0
    for line in lines[i:i+42]:
        lo = line.lower()
        if "projected lineup" in lo or lo.startswith(("status report", "scratched:", "injured:", "suspended:")):
            break
        pieces = [x.strip() for x in re.split(r"\s+(?:--|[–—])\s+", line) if x.strip()]
        known_positions = [positions.get(normalize(n)) for n in pieces] if positions else []
        if (len(pieces) == 2 and forward == 3 and defense == 0
                and len(known_positions) == 2
                and all(p in ("L", "R", "C", "LW", "RW") for p in known_positions)):
            # An official 11F/7D lineup may publish only two fourth-line
            # forwards. Their catalog positions identify them as forwards;
            # the article does not establish their left/center/right order.
            forward += 1
            out.extend((name, "L4", "F") for name in pieces)
        elif len(pieces) == 3 and forward < 4 and defense == 0:
            forward += 1
            for n, role in zip(pieces, ("LW", "C", "RW")):
                out.append((n, "L" + str(forward), role))
        elif len(pieces) == 2 and defense < 3 and forward > 0:
            if any(p in ("C", "L", "R", "LW", "RW") for p in known_positions):
                continue
            defense += 1
            for n in pieces:
                out.append((n, "D" + str(defense), "D"))
        elif (len(pieces) == 1 and defense == 3 and known_positions == ["D"]):
            defense += 1
            out.append((pieces[0], "D4", "D"))
    return out


def read_unavailable(lines, team):
    """Read official article's own scratched/injured/suspended labels only."""
    nickname = TEAMS[team][1].lower()
    matches = [i for i, line in enumerate(lines)
               if line.strip().lower().endswith("projected lineup")
               and nickname in line.strip().lower()]
    if len(matches) != 1:
        return []
    output = []
    for line in lines[matches[0]+1:matches[0]+45]:
        text = line.strip()
        low = text.lower()
        if "projected lineup" in low or low.startswith("status report"):
            break
        for prefix, state in (("scratched:", "SCRATCHED"),
                              ("injured:", "INJURED"),
                              ("suspended:", "OUT")):
            if low.startswith(prefix):
                raw = text[len(prefix):]
                for part in raw.split(","):
                    name = re.sub(r"\s*\([^)]*\)", "", part).strip()
                    if name:
                        output.append((name, state))
    return output


def goalie_id_index(roster):
    """NHL season roster is only an ID catalog; the dated article proves presence."""
    names = {}
    for player in roster.get("goalies") or []:
        first = (player.get("firstName") or {}).get("default") or ""
        last = (player.get("lastName") or {}).get("default") or ""
        name = (first + " " + last).strip()
        if name and player.get("id") is not None:
            names.setdefault(normalize(name), []).append(
                {"id": str(player["id"]), "name": name})
    return {key: values[0] for key, values in names.items()
            if len(values) == 1}


def first_listed_projected_goalie(lines, team, roster_goalies):
    """Resolve an actual goalie name in the *same* dated projected-line section.

    This does not claim a goalie actually played or was CONFIRMED. An unrelated
    later article/status report cannot establish a pre-slate starter.
    """
    nickname = TEAMS[team][1].lower()
    markers = [i for i, line in enumerate(lines)
               if line.strip().lower().endswith("projected lineup")
               and nickname in line.strip().lower()]
    if len(markers) != 1:
        return None
    section = []
    for line in lines[markers[0]+1:markers[0]+45]:
        low = line.strip().lower()
        if ("projected lineup" in low or
                low.startswith(("scratched:", "injured:", "suspended:", "status report"))):
            break
        section.append(line.strip())
    last_pair = max(
        (i for i, line in enumerate(section)
         if len([x for x in re.split(r"\s+(?:--|[–—])\s+", line) if x.strip()]) == 2),
        default=-1)
    if last_pair < 0:
        return None
    seen = []
    for text in section[last_pair+1:]:
        identity = roster_goalies.get(normalize(text))
        if identity and identity["id"] not in [x["id"] for x in seen]:
            seen.append(identity)
    if not seen:
        return None
    return {"goalie": seen[0], "publishedGoalies": seen,
            "firstListedFromOfficialProjectedLineup": True,
            "sourceDoesNotConfirmStarter": True}


def id_index(roster):
    names = {}
    for section in ("forwards", "defensemen"):
        for p in roster.get(section) or []:
            first = (p.get("firstName") or {}).get("default") or ""
            last = (p.get("lastName") or {}).get("default") or ""
            key = normalize(first + " " + last)
            if key:
                names.setdefault(key, []).append(str(p["id"]))
    return {name: ids[0] for name, ids in names.items() if len(ids) == 1}


def position_index(roster):
    """Unique official ID/name positions, used only to interpret article units."""
    identities = id_index(roster)
    candidates = {}
    for section in ("forwards", "defensemen"):
        for p in roster.get(section) or []:
            key = normalize(((p.get("firstName") or {}).get("default") or "") + " " +
                            ((p.get("lastName") or {}).get("default") or ""))
            position = p.get("positionCode") or ("D" if section == "defensemen" else None)
            if key in identities and position in ("L", "R", "C", "LW", "RW", "D"):
                candidates[key] = position
    return candidates


def exact_skater_identity(payload, name):
    """Resolve identity only; the dated article supplies historical membership."""
    if isinstance(payload, dict):
        payload = payload.get("suggestions") or payload.get("players") or []
    if not isinstance(payload, list):
        return None
    exact = [p for p in payload if isinstance(p, dict)
             and normalize(p.get("name") or p.get("fullName") or "") == normalize(name)]
    # Do not choose one same-name person using today's club, active status,
    # search result order, or an inferred historical roster.
    if len(exact) != 1:
        return None
    p = exact[0]
    pid = str(p.get("playerId") or p.get("id") or "")
    position = p.get("positionCode") or p.get("position")
    if not pid.isdigit() or position not in ("L", "R", "C", "LW", "RW", "D"):
        return None
    return {"playerId": pid, "position": position,
            "officialName": p.get("name") or p.get("fullName")}


async def ingest_previews(manifest, database, output):
    raw = json.loads(Path(manifest).read_text())
    calendar = raw["officialSchedule"]
    season = raw["start"][:4] + str(int(raw["start"][:4])+1)
    nhl = NHLClient()
    con = open_db(str(database))
    client = httpx.AsyncClient(timeout=22, follow_redirects=True,
                               headers={"User-Agent": "NHL-True-Blender/1.0 historical source research"})
    sem = asyncio.Semaphore(8)
    errors = []
    teams = {team for row in calendar.values() for game in row.get("games") or []
             for team in (game["away"], game["home"])}
    async def roster(team):
        async with sem:
            try:
                source = await nhl.get(f"roster/{team}/{season}")
                return team, id_index(source["data"]), goalie_id_index(source["data"]), position_index(source["data"]), None
            except Exception as e:
                return team, {}, {}, {}, type(e).__name__
    roster_rows = await asyncio.gather(*(roster(t) for t in teams))
    identities = {team: ids for team, ids, _, _, _ in roster_rows}
    goalie_identities = {team: ids for team, _, ids, _, _ in roster_rows}
    positions = {team: pos for team, _, _, pos, _ in roster_rows}
    errors.extend({"team": team, "reason": err} for team, _, _, _, err in roster_rows if err)
    games = [(day, game) for day, row in calendar.items() for game in row.get("games") or []]
    async def preview(day, game):
        url = preview_url(game, day)
        if not url:
            return day, game, None, None, "UNSUPPORTED_TEAM"
        async with sem:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return day, game, url, response.text, None
            except Exception as e:
                return day, game, url, None, type(e).__name__ + ": " + str(e)[:130]
    retrieved = await asyncio.gather(*(preview(day, game) for day, game in games))
    accepted, rejected, receipts = 0, 0, 0
    projected_goalies = 0
    searched_identities = {}
    recovered_identities = {}
    try:
        for day, game, url, html, error in retrieved:
            if error:
                errors.append({"day": day, "gameId": game.get("id"), "reason": error})
                rejected += 1
                continue
            article = Article()
            article.feed(html)
            article._flush()
            published, modified = publication_clock(article)
            cutoff = game_deadline(game)
            # Do not use a dated ARTICLE as historical proof if it lacks a
            # verified time, or if this living page says it changed later.
            if not published or published > cutoff or (modified and modified > cutoff):
                errors.append({"day": day, "gameId": game.get("id"),
                               "reason": "ARTICLE_PUBLICATION_OR_REVISION_CLOCK_NOT_PRE_CUTOFF",
                               "published": published.isoformat() if published else None,
                               "modified": modified.isoformat() if modified else None})
                rejected += 1
                continue
            valid = False
            for team in (game["away"], game["home"]):
                # Season roster endpoints can omit recalled/traded skaters
                # that the pre-cutoff article explicitly named. Resolve only
                # those names against NHL's independent identity catalog.
                preliminary = read_lines(article.lines, team)
                for name, _, _ in preliminary:
                    key = normalize(name)
                    if key in identities.get(team, {}):
                        continue
                    if key not in searched_identities:
                        try:
                            response = await client.get(
                                "https://search.d3.nhle.com/api/v1/search/player",
                                params={"culture": "en-us", "limit": 100, "q": name})
                            response.raise_for_status()
                            resolved = exact_skater_identity(response.json(), name)
                            searched_identities[key] = ({**resolved, "sourceUrl": str(response.url)}
                                                        if resolved else None)
                        except (httpx.HTTPError, ValueError):
                            searched_identities[key] = None
                    resolved = searched_identities[key]
                    if resolved:
                        identities.setdefault(team, {})[key] = resolved["playerId"]
                        positions.setdefault(team, {})[key] = resolved["position"]
                        recovered_identities[(team, key)] = resolved
                assignments = read_lines(article.lines, team, positions.get(team, {}))
                if len(assignments) < 5:
                    continue
                goalie_projection = first_listed_projected_goalie(
                    article.lines, team, goalie_identities.get(team, {}))
                if goalie_projection:
                    goalie = goalie_projection["goalie"]
                    goalie_payload = {
                        "team": team, "goalieId": goalie["id"],
                        "goalieName": goalie["name"],
                        "status": "EXPECTED",
                        "projectedPreferred": True,
                        "sourceType": "OFFICIAL_NHL_COM_DATED_PROJECTED_LINEUP",
                        "sourceReportDate": day,
                        "sourceArticlePublishedAt": published.isoformat(),
                        "sourceArticleModifiedAt": modified.isoformat() if modified else None,
                        "firstListedFromOfficialProjectedLineup": True,
                        "allPublishedGoalieIds": [
                            x["id"] for x in goalie_projection["publishedGoalies"]],
                        "notConfirmedStarterOrPostgameIdentity": True,
                        "historicalReconstruction": True,
                        "historicalSourceObservedAtCutoffVerified": False,
                        "reconstructedAtUTC": datetime.now(timezone.utc).isoformat(),
                    }
                    digest = hashlib.sha256(
                        json.dumps(goalie_payload, sort_keys=True).encode()).hexdigest()[:16]
                    if ingest(con, {
                        "evidence_id":
                            f"nhl-preview-projected-goalie-{day}-{game.get('id')}-{team}-{goalie['id']}-{digest}",
                        "slate_date": day, "stage": "PROJECTED",
                        "game_id": str(game.get("id") or game.get("gameId")),
                        "player_id": goalie["id"], "kind": "GOALIE_STARTER",
                        "source_url": url,
                        "observed_at": max(published,modified or published).isoformat().replace("+00:00", "Z"),
                        "payload": goalie_payload,
                    }):
                        projected_goalies += 1
                for name, status in read_unavailable(article.lines, team):
                    player_id = identities.get(team, {}).get(normalize(name))
                    if not player_id:
                        continue
                    status_payload = {
                        "status": status,
                        "sourceType": "OFFICIAL_NHL_COM_PROJECTED_LINEUP_ARTICLE",
                        "sourceArticlePublishedAt": published.isoformat(),
                        "sourceArticleModifiedAt": modified.isoformat() if modified else None,
                        "historicalReconstruction": True,
                        "historicalSourceObservedAtCutoffVerified": False,
                        "confirmedDressedNotInferred": True,
                        "reconstructedAtUTC": datetime.now(timezone.utc).isoformat()}
                    status_id = hashlib.sha256(json.dumps(
                        status_payload, sort_keys=True).encode()).hexdigest()[:14]
                    ingest(con, {
                        "evidence_id": f"nhl-preview-status-{day}-{game.get('id')}-{player_id}-{status_id}",
                        "slate_date": day, "stage": "PROJECTED",
                        "game_id": str(game.get("id") or game.get("gameId")),
                        "player_id": player_id, "kind": "PLAYER_STATUS",
                        "source_url": url,
                        "observed_at": max(published,modified or published).isoformat().replace("+00:00", "Z"),
                        "payload": status_payload})
                for name, unit, role in assignments:
                    player_id = identities.get(team, {}).get(normalize(name))
                    if not player_id:
                        continue
                    payload = {
                        "EV": unit, "EVRole": role, "status": "PROJECTED",
                        "sourceParserVersion": 2,
                        "sourceArticleSha256": hashlib.sha256(html.encode()).hexdigest(),
                        "team": team, "playerName": name,
                        "officialPosition": positions.get(team, {}).get(normalize(name)),
                        "officialSeasonRosterIdentityMatched": (team, normalize(name)) not in recovered_identities,
                        "officialNhlPlayerIdentityMatched": True,
                        "identitySourceUrl": (recovered_identities.get((team, normalize(name))) or {}).get("sourceUrl"),
                        "sourceType": "OFFICIAL_NHL_COM_PROJECTED_LINEUP_ARTICLE",
                        "projectedNotConfirmed": True, "PP": None,
                        "sourceArticlePublishedAt": published.isoformat(),
                        "sourceArticleModifiedAt": modified.isoformat() if modified else None,
                        "historicalReconstruction": True,
                        "historicalSourceObservedAtCutoffVerified": False,
                        "originalContentRevisionTimestampConfirmed": modified is not None,
                        "officialSeasonRosterUsedForIdMatchingOnly": True,
                        "reconstructedAtUTC": datetime.now(timezone.utc).isoformat()}
                    item = {
                        "slate_date": day, "stage": "PROJECTED",
                        "game_id": str(game.get("id") or game.get("gameId")),
                        "player_id": player_id, "kind": "PLAYER_DEPLOYMENT",
                        "source_url": url,
                        "observed_at": max(published,modified or published).isoformat().replace("+00:00", "Z"),
                        "payload": payload}
                    signature = hashlib.sha256(json.dumps(
                        payload, sort_keys=True).encode()).hexdigest()[:14]
                    item["evidence_id"] = (
                        f"nhl-preview-{day}-{item['game_id']}-{player_id}-{signature}")
                    if ingest(con, item):
                        receipts += 1
                    valid = True
            if valid:
                accepted += 1
            else:
                rejected += 1
                errors.append({"day": day, "gameId": game.get("id"),
                               "reason": "NO_UNIQUELY_NHL_ID_MATCHED_PROJECTED_LINES"})
        report = {
            "source": "OFFICIAL_NHL_COM_DATED_PREGAME_PROJECTED_LINEUPS",
            "gamesProbed": len(games), "sourceValidGames": accepted,
            "gamesNotCertified": rejected,
            "playerDeploymentReceipts": receipts,
            "sourceVerifiedProjectedGoalieReceipts": projected_goalies,
            "goalieFirstListedInPreviewNeverCalledConfirmed": True,
            "fullCurrentRostersNeverInferred": True,
            "confirmedDeploymentsNeverInferred": True,
            "officialSeasonRosterUsedForIDResolutionOnly": True,
            "exactOfficialSearchIdentitiesRecovered": len(recovered_identities),
            "officialSearchUsedForIdentityOnlyNotHistoricalMembership": True,
            "publicationAndModificationClockRequiredWhenProvided": True,
            "errors": errors[:200]}
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(report, indent=2))
        print(json.dumps({k:v for k,v in report.items() if k != "errors"}, sort_keys=True))
    finally:
        con.close()
        await nhl.close()
        await client.aclose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest", type=Path)
    p.add_argument("--database", type=Path, default=Path("state/true_blender.sqlite"))
    p.add_argument("--output", type=Path,
                   default=Path("state/replay/nhl-preview-ingestion.json"))
    a = p.parse_args()
    asyncio.run(ingest_previews(a.manifest, a.database, a.output))


if __name__ == "__main__":
    main()
