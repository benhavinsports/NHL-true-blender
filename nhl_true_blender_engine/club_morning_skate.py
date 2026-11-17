"""Independent same-day club-beat eyewitness starting-goalie research.

Official NHL goalie roster IDs and date-specific matchup pages are mandatory.
The linked article itself, not a prediction percentage, must report the exact
goalie by full name first off at the game-day morning skate. This is EXPECTED
only; neither a source report nor the clock is NHL team confirmation.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
import httpx
from .enrichment import ingest
from .secondary_sources import TEAM_SLUGS

# Supported editorial club-beat provider; never a goalie or scorer override.
REPORT_DOMAINS={"lakingsinsider.com":"LAK"}

class _Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls=[]
        self.text=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1
        elif not self.hidden and tag in ("div","article","h1","h2","h3","p","li","br"):
            self.text.append("\n")
        if tag=="a":
            href=dict(attrs).get("href") or ""
            if href:self.urls.append(href)
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg"):
            self.hidden=max(0,self.hidden-1)
        elif not self.hidden and tag in ("div","article","h1","h2","h3","p","li","br"):
            self.text.append("\n")
    def handle_data(self,data):
        if not self.hidden and data.strip():
            self.text.append(" "+data.strip()+" ")

def linked_same_day_club_reports(source_html,date):
    """Only real date-stamped independent articles LINKED by today's DFO."""
    year,month,day=(int(x) for x in date.split("-"))
    prefix=f"/{year:04d}/{month:02d}/{day:02d}/"
    links=_Extract()
    links.feed(source_html or "")
    output={}
    for url in links.urls:
        parts=urlparse(url)
        domain=(parts.hostname or "").removeprefix("www.").lower()
        team=REPORT_DOMAINS.get(domain)
        if parts.scheme!="https" or not team or not parts.path.startswith(prefix):
            continue
        output[url]=team
    return sorted(output.items())

def parse_first_off_club_article(article_html,source_url,date,game,team):
    """Return the SINGLE first-off exact-roster goalie for this exact game."""
    domain=(urlparse(source_url).hostname or "").removeprefix("www.").lower()
    if REPORT_DOMAINS.get(domain)!=team:
        return None
    stamp=datetime.strptime(date,"%Y-%m-%d")
    parts=urlparse(source_url)
    if not parts.path.startswith(stamp.strftime("/%Y/%m/%d/")):
        return None
    if team not in (game["away"],game["home"]):
        return None
    parser=_Extract()
    parser.feed(article_html or "")
    body=" ".join(" ".join(parser.text).split())
    away=TEAM_SLUGS.get(game["away"],"").replace("-"," ")
    home=TEAM_SLUGS.get(game["home"],"").replace("-"," ")
    # Editorial articles may include other games in sidebars. Demand the
    # WHO: exact away/home paired matchup in this dated article itself.
    matchup=(r"\bWHO\s*:\s*"+re.escape(away)+
       r"\s*(?:\([^)]*\))?\s*@\s*"+re.escape(home)+r"\b")
    if not re.search(matchup,body,re.I):
        return None
    # This report is from the Lakings Insider and describes the Kings' own
    # morning skate BEFORE the opposing team's separate pregame section.
    section=re.split(r"\bBRUINS VITALS\s*:",body,flags=re.I)[0]
    roster=((game.get("rosters") or {}).get(team) or {}).get("data") or {}
    hits=[]
    for goalie in roster.get("goalies") or []:
        name=goalie.get("name") or ""
        if not name or not goalie.get("id"):
            continue
        # Direct observed "off the ice first" wording, not editorial
        # generic projected-order or last-game goalkeeper observations.
        proof=(r"\b(?:Goaltender\s+)?"+re.escape(name)+
               r"\s+was\s+(?:the\s+)?(?:off\s+the\s+ice\s+first|"
               r"first\s+(?:goalie|goaltender)\s+off(?:\s+the\s+ice)?)\b")
        if re.search(proof,section,re.I):
            hits.append(goalie)
    if len(hits)!=1:
        return None
    return {"gameId":str(game["id"]),"team":team,
        "goalieId":str(hits[0]["id"]),"goalieName":hits[0]["name"],
        "status":"EXPECTED","projectedPreferred":True,
        "datedEyewitnessMorningSkateFirstOff":True,
        "sourceReportDate":date,
        "morningSkateSourceUrls":[source_url],
        "sourceType":"DATED_DIRECT_CLUB_BEAT_MORNING_SKATE_REPORT",
        "neverCalledTeamConfirmed":True}

async def collect_linked_club_reports(con,snapshot,date,stage,source_html):
    urls=linked_same_day_club_reports(source_html,date)
    games=snapshot.get("games") or []
    results=[];errors=[];attempts=[]
    async with httpx.AsyncClient(timeout=18,follow_redirects=True,
        headers={"User-Agent":"Mozilla/5.0 (NHLTrueBlender/1.0)"}) as client:
        async def read(url,team):
            try:
                res=await client.get(url)
                res.raise_for_status()
                return url,team,res.text,None
            except (httpx.HTTPError,ValueError) as err:
                return url,team,None,type(err).__name__
        pages=await asyncio.gather(*(read(url,team) for url,team in urls[:8]))
    observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for url,team,html,error in pages:
        attempts.append({"sourceUrl":url,"team":team,
                         "status":"FETCH_FAILED" if error else "FETCHED"})
        if error:
            errors.append({"sourceUrl":url,"error":error})
            continue
        for game in games:
            item=parse_first_off_club_article(html,url,date,game,team)
            if item is None:
                continue
            payload={k:v for k,v in item.items() if k!="gameId"}
            key=hashlib.sha256(json.dumps({
                "date":date,"stage":stage,"gameId":item["gameId"],
                "sourceUrl":url,"payload":payload},
                sort_keys=True,separators=(",",":")).encode()).hexdigest()[:18]
            ingest(con,{"evidence_id":f"club-first-off-v1-{key}",
                "slate_date":date,"stage":stage,"game_id":item["gameId"],
                "kind":"GOALIE_STARTER","source_url":url,
                "observed_at":observed,"payload":payload})
            results.append(item)
    return {"status":"SOURCED_REPORTS_COLLECTED","sourceAttempts":attempts,
        "matchedOfficialGoalieIds":len(results),"matched":results,
        "sourceFailures":errors,
        "unknownOrContradictoryGoaliesNeverInferred":True,
        "neverTurnsExpectedIntoConfirmed":True}
