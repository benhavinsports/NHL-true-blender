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

def parse_projected_goalies(html,game,date):
    if not isinstance(html,str) or "projected lineup" not in html.lower():
        return {}
    content=article_text(html)
    day=datetime.strptime(date,"%Y-%m-%d")
    published=f"{day.strftime('%B')} {day.day}, {day.year}"
    if published.casefold() not in content.casefold():
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

def parse_official_unavailable(html,game,date):
    """Only explicitly listed injured/scratched skaters on a dated NHL page.

    Match full names to official current-roster IDs. Not being mentioned or
    not appearing on a published line is NOT evidence that a skater is out.
    Goalie scratch listings never enter the scorer-skater availability pool.
    """
    if not isinstance(html,str) or "projected lineup" not in html.lower():
        return []
    body=article_text(html)
    day=datetime.strptime(date,"%Y-%m-%d")
    if f"{day.strftime('%B')} {day.day}, {day.year}".casefold() not in body.casefold():
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


async def collect_nhl_projected_goalies(con,snapshot,date,stage):
    """Review all known source variants; unmatched URLs never establish a starter."""
    games=snapshot.get("games",[])
    year=int(date[:4]) if int(date[5:7])>=9 else int(date[:4])-1
    urls={f"https://www.nhl.com/news/nhl-lineup-projections-{year}-{str(year+1)[-2:]}-season"}
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
    attempts=[];found=0;seen={};conflicts=[];unavailable=[]
    for url,html,error in pages:
        attempts.append({"url":url,"status":"FETCH_FAILED" if error else "FETCHED",
                         "error":error})
        if not html:
            continue
        for game in games:
            # A real, dated NHL.com "Injured:" or "Scratched:" list
            # disqualifies that exact skater from teammate rivalry checks.
            # Every source attribution is retained; missing names stay unknown.
            for item in parse_official_unavailable(html,game,date):
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
            for team,data in parse_projected_goalies(html,game,date).items():
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
            "explicitInjuryAndScratchReceipts":len(unavailable),
            "unavailablePlayerExamples":unavailable[:12],
            "contradictionsKept":conflicts,
            "neverPromotesProjectionToConfirmation":True}
