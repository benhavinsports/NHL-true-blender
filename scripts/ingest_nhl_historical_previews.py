"""Ingest verifiable pregame NHL.com projected lineup deployments (not rosters).

This source is only valid when official article publication metadata has an
offset-aware timestamp BEFORE the original slate cutoff. A date-only article
or page modified after cutoff is excluded; no postgame correction is allowed.
Official historical season rosters resolve player IDs only, never establish
a dated complete roster or a confirmed lineup.
"""
from __future__ import annotations
import argparse
import asyncio
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


def read_lines(lines, team):
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
        pieces = [x.strip() for x in re.split(r"\s+--\s+", line) if x.strip()]
        if len(pieces) == 3 and forward < 4 and defense == 0:
            forward += 1
            for n, role in zip(pieces, ("LW", "C", "RW")):
                out.append((n, "L" + str(forward), role))
        elif len(pieces) == 2 and defense < 3 and forward > 0:
            defense += 1
            for n in pieces:
                out.append((n, "D" + str(defense), "D"))
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
                return team, id_index(source["data"]), None
            except Exception as e:
                return team, {}, type(e).__name__
    roster_rows = await asyncio.gather(*(roster(t) for t in teams))
    identities = {team: ids for team, ids, _ in roster_rows}
    errors.extend({"team": team, "reason": err} for team, _, err in roster_rows if err)
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
            cutoff = min(
                utc(g.get("startTimeUTC") or g.get("startUTC"))
                for g in calendar[day]["games"]) - timedelta(minutes=5)
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
                assignments = read_lines(article.lines, team)
                if len(assignments) < 5:
                    continue
                for name, status in read_unavailable(article.lines, team):
                    player_id = identities.get(team, {}).get(normalize(name))
                    if not player_id:
                        continue
                    status_payload = {
                        "status": status,
                        "sourceType": "OFFICIAL_NHL_COM_PROJECTED_LINEUP_ARTICLE",
                        "sourceArticlePublishedAt": published.isoformat(),
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
                        "observed_at": published.isoformat().replace("+00:00", "Z"),
                        "payload": status_payload})
                for name, unit, role in assignments:
                    player_id = identities.get(team, {}).get(normalize(name))
                    if not player_id:
                        continue
                    payload = {
                        "EV": unit, "EVRole": role, "status": "PROJECTED",
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
                        "observed_at": published.isoformat().replace("+00:00", "Z"),
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
            "fullCurrentRostersNeverInferred": True,
            "confirmedDeploymentsNeverInferred": True,
            "officialSeasonRosterUsedForIDResolutionOnly": True,
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
