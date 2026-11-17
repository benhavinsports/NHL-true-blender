"""Dated, matchup-scoped projected NHL starter research.

The main lineup markdown can still display yesterday's slate early in the
morning. This independent same-day source supplies EXPECTED goalie IDs only;
it never invents confirmation, skater deployment, or a scorer selection.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
import unicodedata

import httpx

from .enrichment import ingest

ROOT = "https://daily.hockey/starting-goalies/"


def normalized(value):
    clean=unicodedata.normalize("NFKD",str(value or ""))
    return re.sub(r"[^a-z0-9]+"," ",
        clean.encode("ascii","ignore").decode().casefold()).strip()


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1

    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg") and self.hidden:
            self.hidden-=1

    def handle_data(self,data):
        if not self.hidden and data.strip():
            self.parts.append(data.strip())


def _lookup_goalie(surname, roster):
    """Never resolve a surname to multiple possible rostered goalies."""
    token=normalized(surname)
    if not token:
        return None
    matches=[]
    for p in roster or []:
        name=normalized(p.get("name"))
        if name==token or name.endswith(" "+token):
            matches.append(p)
    return matches[0] if len(matches)==1 else None


def parse_dated_projections(html, date, games, diagnostics=None):
    """Parse only an exact-date matchup block, never a nav link or old slate.

    The source presents TEAM · #jersey Surname followed by the source's own
    confidence label. It is an algorithmic PROJECTED identity, not a confirmed
    NHL starter. No manual player/goalie names are embedded in the parser.
    """
    if not isinstance(html,str) or not html:
        if diagnostics is not None:
            diagnostics.extend({"gameId":str(g["id"]),"reason":"EMPTY_SOURCE"}
                               for g in games)
        return [],"EMPTY_SOURCE"
    text_parser=_VisibleText()
    text_parser.feed(html)
    flat=re.sub(r"\s+"," "," ".join(text_parser.parts))
    day=datetime.strptime(date,"%Y-%m-%d")
    date_rx=rf"\b{day.strftime('%B')}\s+{day.day},?\s+{day.year}\b"
    if not re.search(date_rx,flat,re.I) or "starting goalies" not in flat.lower():
        if diagnostics is not None:
            diagnostics.extend({"gameId":str(g["id"]),
                                "reason":"SOURCE_SLATE_DATE_UNVERIFIED"}
                               for g in games)
        return [],"SOURCE_SLATE_DATE_UNVERIFIED"
    found=[]
    for game in games:
        teams=(game["away"],game["home"])
        header=re.compile(rf"\b{re.escape(teams[0])}\s*@\s*{re.escape(teams[1])}\b")
        reason="SOURCE_MATCHUP_NOT_FOUND"
        for m in header.finditer(flat):
            reason="STARTER_FIELDS_NOT_PARSED"
            # The page includes a navigation menu. Match all starter fields
            # from a single GAME card, ending at the next fixture header.
            upcoming=re.search(r"\b[A-Z]{2,3}\s*@\s*[A-Z]{2,3}\b",flat[m.end():])
            stop=m.end()+upcoming.start() if upcoming else len(flat)
            section=flat[m.end():min(stop,m.end()+2000)]
            picks=[]
            for team in teams:
                pattern=rf"\b{re.escape(team)}\s*[\u00b7\u2022]\s*#\s*\d+\s*([A-Za-z][A-Za-z' -]*?)\s+(\d{{1,3}})\s*%\s*(Likely|Leaning|Toss-up|Confirmed|Started)"
                got=re.search(pattern,section,re.I)
                if not got:
                    break
                roster=((game.get("rosters") or {}).get(team) or {}).get("data") or {}
                player=_lookup_goalie(got.group(1),roster.get("goalies"))
                if not player:
                    reason="OFFICIAL_GOALIE_ID_UNMATCHED_OR_AMBIGUOUS"
                    break
                probability=int(got.group(2))
                if not 0<=probability<=100:
                    break
                label=got.group(3).upper()
                # Even the source's "confirmed" label is a model/website
                # claim at this stage; do NOT claim official confirmation.
                picks.append({
                    "gameId":str(game["id"]),"team":team,
                    "goalieId":str(player["id"]),"goalieName":player["name"],
                    "sourceLabel":label,"sourceProbability":probability,
                    "projectedPreferred":label in ("LIKELY","LEANING"),
                })
            if len(picks)==2:
                found.extend(picks)
                reason="MATCHED"
                break
        if diagnostics is not None:
            diagnostics.append({"gameId":str(game["id"]),
                                "matchup":teams[0]+"@"+teams[1],
                                "reason":reason})
    return found,("DATED_MATCHUPS_PARSED" if found else "NO_MATCHED_GOALIES")


async def collect_dated_goalie_projections(con, snapshot, date, stage):
    url=ROOT+date
    attempts=0
    diagnostics=[]
    try:
        async with httpx.AsyncClient(timeout=18,follow_redirects=True,
                headers={"User-Agent":"Mozilla/5.0 (NHLTrueBlender/1.0)"}) as client:
            for attempt in range(3):
                attempts=attempt+1
                try:
                    reply=await client.get(url)
                    reply.raise_for_status()
                    break
                except (httpx.TimeoutException,httpx.TransportError,
                        httpx.HTTPStatusError) as exc:
                    # Retry recoverable transport/rate-limit/server failures,
                    # not 404, an invalid slate date, or a bad page schema.
                    transient=(not isinstance(exc,httpx.HTTPStatusError)
                        or exc.response.status_code in (429,500,502,503,504))
                    if not transient or attempt==2:
                        raise
                    await asyncio.sleep(0.4*(attempt+1))
            candidates,status=parse_dated_projections(
                reply.text,date,snapshot.get("games",[]),diagnostics)
    except (httpx.HTTPError,ValueError) as exc:
        return {"status":"SOURCE_UNAVAILABLE","source":url,
                "error":f"{type(exc).__name__}: {str(exc)[:160]}",
                "projectedGoalieReceipts":0,
                "boundedRetryCount":max(0,attempts-1)}
    observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in candidates:
        ingest(con,{
            "evidence_id":f"dated-projected-goalie-{date}-{stage}-{item['gameId']}-{item['team']}-{item['goalieId']}-{observed}",
            "slate_date":date,"stage":stage,"game_id":item["gameId"],
            "kind":"GOALIE_STARTER","source_url":url,"observed_at":observed,
            "payload":{
                "team":item["team"],"goalieId":item["goalieId"],
                "goalieName":item["goalieName"],"status":"EXPECTED",
                "identityMatched":True,
                "projectedPreferred":item["projectedPreferred"],
                "starterSourceStatus":"DATED_SECONDARY_ALGORITHMIC_PROJECTION",
                "sourceConfidenceLabel":item["sourceLabel"],
                "sourceReportedProbability":item["sourceProbability"],
                "notTeamConfirmed":True,
                "publishedAsOfSlateDate":date,
                "sourceEventDoesNotSelectScorers":True}
        })
    return {"status":status,"source":url,"asOf":observed,
            "boundedRetryCount":max(0,attempts-1),
            "matchupResearch":diagnostics,
            "matchupResearchReasons":{reason:sum(d["reason"]==reason for d in diagnostics)
                  for reason in sorted({d["reason"] for d in diagnostics})},
            "projectedGoalieReceipts":len(candidates),
            "gamesWithBothGoalieProjections":len({x["gameId"] for x in candidates}),
            "originalSourceLabelsPreserved":True,
            "noProjectedGoalieCalledConfirmed":True}
