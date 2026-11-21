"""Dated NHL.com projected-goalie fallback; projected is never confirmed."""
from __future__ import annotations
import asyncio
import hashlib
from datetime import datetime,timezone
from html.parser import HTMLParser
import re
import unicodedata
import httpx
from .enrichment import ingest
from .secondary_sources import TEAM_SLUGS

NICKNAMES={"CBJ":"blue jackets","VGK":"golden knights"}
class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1
        if tag in ("p","h1","h2","h3","h4","li","div","br","section"):
            self.parts.append("\n")
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg"):
            self.hidden=max(0,self.hidden-1)
        if tag in ("p","h1","h2","h3","h4","li","section"):
            self.parts.append("\n")
    def handle_data(self,data):
        if not self.hidden:
            self.parts.append(data)

def article_text(html):
    parser=Text()
    parser.feed(html)
    return re.sub(r"[ \t]+"," ","".join(parser.parts))

def normalized(value):
    ascii_text=unicodedata.normalize("NFKD",str(value)).encode(
        "ascii","ignore").decode().casefold()
    # HTML paragraphs are separated by line breaks. Preserve them as word
    # boundaries; deleting newlines glued "Nikita Tolopilo" to the prior
    # skater name and made exact roster ID matches impossible.
    return re.sub(r"[^a-z0-9]+"," ",ascii_text).strip()

def preview_urls(game,date):
    day=datetime.strptime(date,"%Y-%m-%d")
    away=TEAM_SLUGS.get(game["away"])
    home=TEAM_SLUGS.get(game["home"])
    if not away or not home:
        return []
    suffix=day.strftime("%B").lower()+f"-{day.day}-{day.year}"
    return [f"https://www.nhl.com/news/{away}-{home}-game-preview-{suffix}",
            f"https://www.nhl.com/news/{away}-{home}-projected-lineups-{suffix}"]


def _article_date_targets_game(html,game,date,source_url=None):
    """Independently verify publication time vs the EXACT preview matchup.

    A day-before NHL.com preview may describe tomorrow's scheduled game.
    That is not a historical replay and does not require inventing the
    article's publication date. Only an exact official game preview URL
    *and* its displayed away-at-home heading can authorize this exception.
    Season-long articles cannot borrow the game-preview date.
    """
    if not isinstance(html,str):
        return False
    try:
        requested=datetime.strptime(date,"%Y-%m-%d").date()
    except (TypeError,ValueError):
        return False
    content=article_text(html)
    match=re.search(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s*(20\d{2})\b",
        content,re.I)
    if match is None:
        return False
    try:
        published=datetime.strptime(match.group(0),"%B %d, %Y").date()
    except ValueError:
        return False
    # Daily NHL.com page may legitimately be published the evening before a
    # real game. Unlike a generic roster feed, its own day header AND exact
    # official opponent pair are independently verifiable in the article.
    season=requested.year if requested.month>=9 else requested.year-1
    season_url=(f"https://www.nhl.com/news/nhl-lineup-projections-"
                f"{season}-{str(season+1)[-2:]}-season")
    if source_url==season_url:
        from deployment_sources import _nhl_article_game_day_verified
        return _nhl_article_game_day_verified(
            html,date,TEAM_SLUGS.get(game["away"]),TEAM_SLUGS.get(game["home"]))
    source_is_preview=(isinstance(source_url,str) and
                       source_url in preview_urls(game,date))
    # An explicitly requested official preview may be published one or two
    # days ahead. An unrelated preview must never authenticate this matchup.
    if source_url and "game-preview-" in source_url or (
            source_url and "projected-lineups-" in source_url):
        if not source_is_preview:
            return False
    if published==requested:
        return True
    if not source_is_preview or not 0 < (requested-published).days <= 2:
        return False
    away=NICKNAMES.get(game["away"],TEAM_SLUGS.get(game["away"],"").split("-")[-1])
    home=NICKNAMES.get(game["home"],TEAM_SLUGS.get(game["home"],"").split("-")[-1])
    direct=(r"\b"+re.escape(away)+r"\s+(?:at|vs\.?)\s+"+
            re.escape(home)+r"\s+projected\s+lineups\b")
    reverse=(r"\b"+re.escape(home)+r"\s+(?:at|vs\.?)\s+"+
             re.escape(away)+r"\s+projected\s+lineups\b")
    if not (re.search(direct,content,re.I) or re.search(reverse,content,re.I)):
        return False
    return all(re.search(r"\b"+re.escape(NICKNAMES.get(team,
                      TEAM_SLUGS.get(team,"").split("-")[-1]))+
                  r"\s+projected lineup\b",content,re.I)
               for team in (game["away"],game["home"]))


def parse_projected_goalies(html,game,date,source_url=None):
    if not isinstance(html,str) or "projected lineup" not in html.lower():
        return {}
    content=article_text(html)
    if not _article_date_targets_game(html,game,date,source_url):
        return {}
    out={}
    for team in (game["away"],game["home"]):
        nickname=NICKNAMES.get(team,TEAM_SLUGS.get(team,"").split("-")[-1])
        start=re.search(r"\b"+re.escape(nickname)+r"\s+projected lineup\b",content,re.I)
        if not start:
            continue
        tail=content[start.end():]
        end=re.search(r"\b(?:scratched|injured|status report)\s*:|\b[a-z ]{2,36}\s+projected lineup\b",tail,re.I)
        section=tail[:end.start()] if end else tail[:2400]
        roster=(game.get("rosters",{}).get(team) or {}).get("data") or {}
        matched=[]
        scoped=normalized(section)
        for goalie in roster.get("goalies",[]):
            name=normalized(goalie.get("name"))
            if len(name)<6:
                continue
            m=re.search(r"(?<![a-z])"+re.escape(name)+r"(?![a-z])",scoped)
            if m:
                matched.append((m.start(),str(goalie["id"]),goalie["name"]))
        matched.sort()
        if matched and (len(matched)==1 or matched[0][0]!=matched[1][0]):
            out[team]={"goalieId":matched[0][1],"name":matched[0][2],
                       "publishedGoalies":[x[2] for x in matched]}
    return out

def parse_official_unavailable(html,game,date,source_url=None):
    """Only explicitly listed injured/scratched skaters on a dated NHL page.

    Match full names to official current-roster IDs. Not being mentioned or
    not appearing on a published line is NOT evidence that a skater is out.
    Goalie scratch listings never enter the scorer-skater availability pool.
    """
    if not isinstance(html,str) or "projected lineup" not in html.lower():
        return []
    body=article_text(html)
    if not _article_date_targets_game(html,game,date,source_url):
        return []
    out=[]
    for team in (game["away"],game["home"]):
        nickname=NICKNAMES.get(team,TEAM_SLUGS.get(team,"").split("-")[-1])
        marker=re.search(r"\b"+re.escape(nickname)+r"\s+projected lineup\b",body,re.I)
        if not marker:
            continue
        tail=body[marker.end():]
        following=re.search(r"\b[a-z ]{2,36}\s+projected lineup\b|\bstatus report\b",
                            tail,re.I)
        section=tail[:following.start()] if following else tail[:4000]
        roster=((game.get("rosters",{}).get(team) or {}).get("data") or {}).get("players",[])
        for line in section.splitlines():
            m=re.match(r"^\s*(Scratched|Injured):\s*(.+)$",line,re.I)
            if not m:
                continue
            status="SCRATCHED" if m.group(1).lower()=="scratched" else "INJURED"
            for part in m.group(2).split(","):
                listed=normalized(re.sub(r"\([^)]*\)","",part))
                if not listed:
                    continue
                matches=[p for p in roster if normalized(p.get("name"))==listed]
                if len(matches)!=1:
                    continue
                out.append({"team":team,"playerId":str(matches[0]["id"]),
                            "name":matches[0]["name"],"status":status})
    # Contradictory independent lines do not prove someone unavailable.
    grouped={}
    for item in out:
        grouped.setdefault((item["team"],item["playerId"]),[]).append(item)
    return [v[0] for v in grouped.values()
            if len({x["status"] for x in v})==1]


def parse_projected_deployment(html, game, date, source_url=None):
    """Read explicit, identity-matched units in an NHL.com preview.

    Line combinations remain source-PROJECTED, never confirmed or dressed.
    A team's official current roster resolves identity but does not establish
    that a player is participating tonight. Ambiguous names stay unresolved.
    """
    if not isinstance(html, str) or "projected lineup" not in html.lower():
        return []
    body = article_text(html)
    if not _article_date_targets_game(html,game,date,source_url):
        return []
    output = []
    for team in (game["away"], game["home"]):
        nickname = NICKNAMES.get(team, TEAM_SLUGS.get(team, "").split("-")[-1])
        heading = re.search(r"\b" + re.escape(nickname) + r"\s+projected lineup\b", body, re.I)
        if not heading:
            continue
        tail = body[heading.end():]
        end = re.search(r"\b(?:scratched|injured|status report)\s*:|"
                        r"\b[a-z ]{2,36}\s+projected lineup\b", tail, re.I)
        section = tail[:end.start()] if end else tail[:2400]
        roster = ((game.get("rosters") or {}).get(team) or {}).get("data") or {}
        indexed = {}
        for player in roster.get("players") or []:
            key = normalized(player.get("name"))
            if key and player.get("id") and player.get("position") in ("C", "L", "R", "LW", "RW", "D"):
                indexed.setdefault(key, []).append(player)
        unique = {key: values[0] for key, values in indexed.items() if len(values) == 1}
        forward_line = 0
        defense_pair = 0
        used = set()
        for row in section.splitlines():
            # NHL.com normally uses "Name -- Name -- Name". Preserve all
            # explicit dash separators; never split a hyphenated surname.
            names = [name.strip() for name in re.split(r"\s+(?:--|—|–)\s+", row.strip())]
            if len(names) not in (1, 2, 3):
                continue
            skaters = [unique.get(normalized(name)) for name in names]
            if any(player is None for player in skaters):
                continue
            ids = {str(player["id"]) for player in skaters}
            if len(ids) != len(skaters) or ids & used:
                continue
            if len(skaters) == 3:
                if forward_line >= 4 or not all(player["position"] != "D" for player in skaters):
                    continue
                forward_line += 1
                ev = f"F{forward_line}"
            elif (len(skaters) == 2 and forward_line == 3 and defense_pair == 0
                  and all(player["position"] != "D" for player in skaters)):
                # Source-published 11F/7D: the fourth forward unit has two
                # named skaters. Their roster positions rule out a D pair.
                forward_line += 1
                ev = "F4"
            elif len(skaters) == 2:
                if defense_pair >= 3 or not all(player["position"] == "D" for player in skaters):
                    continue
                defense_pair += 1
                ev = f"D{defense_pair}"
            else:
                if defense_pair != 3 or skaters[0]["position"] != "D":
                    continue
                defense_pair += 1
                ev = "D4"
            used.update(ids)
            for player in skaters:
                output.append({"team": team, "playerId": str(player["id"]),
                               "EV": ev, "status": "PROJECTED",
                               "sourceType": "NHL_OFFICIAL_PUBLISHED_PROJECTED_LINE_COMBINATION",
                               "projectedNotConfirmed": True,
                               "doesNotEstablishDressedOrPP": True})
    return output


async def collect_nhl_projected_goalies(con,snapshot,date,stage):
    """Review all known source variants; unmatched URLs never establish a starter."""
    games=snapshot.get("games",[])
    year=int(date[:4]) if int(date[5:7])>=9 else int(date[:4])-1
    season_url=f"https://www.nhl.com/news/nhl-lineup-projections-{year}-{str(year+1)[-2:]}-season"
    urls={season_url}
    for game in games:
        urls.update(preview_urls(game,date))
    async with httpx.AsyncClient(timeout=18,follow_redirects=True,
        headers={"User-Agent":"Mozilla/5.0 (NHLTrueBlender/1.0)"}) as client:
        sem=asyncio.Semaphore(3)
        async def fetch(url):
            async with sem:
                try:
                    response=await client.get(url)
                    response.raise_for_status()
                    return url,response.text,None
                except (httpx.HTTPError,ValueError) as exc:
                    return url,None,f"{type(exc).__name__}: {str(exc)[:120]}"
        pages=await asyncio.gather(*(fetch(url) for url in sorted(urls)))
    attempts=[];found=0;seen={};conflicts=[];unavailable=[];deployment_count=0
    for url,html,error in pages:
        attempts.append({"url":url,"status":"FETCH_FAILED" if error else "FETCHED",
                         "error":error})
        if not html:
            continue
        for game in games:
            # A real, dated NHL.com "Injured:" or "Scratched:" list
            # disqualifies that exact skater from teammate rivalry checks.
            # Every source attribution is retained; missing names stay unknown.
            for item in parse_official_unavailable(html,game,date,url):
                observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
                digest=hashlib.sha256(url.encode()).hexdigest()[:12]
                ingest(con,{"evidence_id":f"nhl-projected-unavailable-{date}-{stage}-{game['id']}-{item['playerId']}-{item['status']}-{digest}",
                    "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                    "player_id":item["playerId"],"kind":"PLAYER_STATUS",
                    "source_url":url,"observed_at":observed,"payload":{
                        "status":item["status"],"sourceType":"NHL_OFFICIAL_PROJECTED_LINEUP_UNAVAILABLE",
                        "officialRosterIdMatched":True,
                        "publishedAsOfSlateDate":date,
                        "notAbsenceBased":True}})
                unavailable.append({"gameId":str(game["id"]),
                                    "playerId":item["playerId"],
                                    "status":item["status"],"sourceUrl":url})
            # The same dated NHL.com page already fetched for starter research
            # also contains explicit EV line trios/defense pairs. The separate
            # generic deployment collector previously imported ZERO from
            # these official pages because its article parser did not match
            # the source headings. Attach only while the matchup is FUTURE.
            start=game.get("startUTC") or game.get("startTimeUTC")
            start_dt=(datetime.fromisoformat(start.replace("Z","+00:00"))
                      if isinstance(start,str) else None)
            still_pregame=(start_dt is not None and
                           start_dt.tzinfo is not None and
                           start_dt > datetime.now(timezone.utc) and
                           game.get("gameState") in ("FUT","PRE"))
            # The season news article is allowed ONLY for the game's own
            # published day heading + exact scheduled opponent. Other team
            # sections, yesterday's game and future result knowledge remain
            # barred, and these roles stay PROJECTED until independently
            # confirmed by a separate source.
            article_matches=(url==season_url and
                             _article_date_targets_game(html,game,date,url))
            if still_pregame and (url in preview_urls(game,date) or
                                  article_matches):
                for row in parse_projected_deployment(html,game,date,url):
                    observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
                    digest=hashlib.sha256(
                        f"{url}|{row['playerId']}|{row['EV']}".encode()
                        ).hexdigest()[:16]
                    ingest(con,{
                        "evidence_id":f"nhl-official-projected-line-{date}-{stage}-{game['id']}-{digest}-{observed}",
                        "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                        "player_id":row["playerId"],"kind":"PLAYER_DEPLOYMENT",
                        "source_url":url,"observed_at":observed,
                        "payload":row})
                    deployment_count+=1
            for team,data in parse_projected_goalies(html,game,date,url).items():
                key=(str(game["id"]),team)
                if key in seen and seen[key]!=data["goalieId"]:
                    conflicts.append({"gameId":key[0],"team":team,
                                      "previousGoalieId":seen[key],
                                      "newGoalieId":data["goalieId"],"sourceUrl":url})
                seen[key]=data["goalieId"]
                observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
                digest=hashlib.sha256(url.encode()).hexdigest()[:12]
                ingest(con,{"evidence_id":f"nhl-projected-goalie-{date}-{stage}-{game['id']}-{team}-{data['goalieId']}-{digest}",
                    "slate_date":date,"stage":stage,"game_id":str(game["id"]),
                    "kind":"GOALIE_STARTER","source_url":url,
                    "observed_at":observed,"payload":{
                        "team":team,"goalieId":data["goalieId"],
                        "goalieName":data["name"],"status":"EXPECTED",
                        "projectedPreferred":True,
                        "starterSourceStatus":"NHL_OFFICIAL_PROJECTED_LINEUP",
                        "publishedGoalies":data["publishedGoalies"],
                        "projectedNotConfirmed":True,"identityMatched":True}})
                found+=1
    return {"status":"SOURCE_RESEARCH_COMPLETED",
            "sourceType":"NHL_OFFICIAL_PUBLISHED_PROJECTED_LINEUP",
            "sourceAttempts":attempts,"projectedGoalieReceipts":found,
            "officialProjectedEVReceipts":deployment_count,
            "officialLineupNeverPromotedToConfirmed":True,
            "explicitInjuryAndScratchReceipts":len(unavailable),
            "unavailablePlayerExamples":unavailable[:12],
            "contradictionsKept":conflicts,
            "neverPromotesProjectionToConfirmation":True}
