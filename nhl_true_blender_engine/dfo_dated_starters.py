"""Dated independent starting-goalie research (Daily Faceoff public HTML).

Never manufactures a starter from team depth charts, absence, win odds, or a
generic goalie mention. Only an exact dated matchup and standalone source
starter identity matched uniquely to an official NHL roster goalie ID becomes
GOALIE_STARTER evidence. This collector does NOT select a scoring recipient.
"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
import unicodedata

import httpx

from .enrichment import ingest
from .secondary_sources import TEAM_SLUGS

URL="https://www.dailyfaceoff.com/starting-goalies/{date}"
STARTER_LABELS={"Confirmed":"CONFIRMED","Likely":"EXPECTED","Projected":"EXPECTED"}
BLOCK_TAGS={"div","article","section","p","h1","h2","h3","h4","h5","li","br","main","header","footer"}

class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks=[]
        self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript","svg"):
            self.hidden+=1
        elif tag in BLOCK_TAGS and not self.hidden:
            self.chunks.append("\n")
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript","svg"):
            self.hidden=max(0,self.hidden-1)
        elif tag in BLOCK_TAGS and not self.hidden:
            self.chunks.append("\n")
    def handle_data(self,value):
        if not self.hidden and value.strip():
            self.chunks.append(value.strip())

def _normalize(value):
    text=unicodedata.normalize("NFKD",str(value or ""))
    return re.sub(r"[^a-z0-9]+"," ",
        text.encode("ascii","ignore").decode().casefold()).strip()

def _club_name(abbr):
    slug=TEAM_SLUGS.get(abbr)
    return slug.replace("-"," ").title() if slug else None

def _expected_utc(game):
    try:
        d=datetime.fromisoformat(str(game["startUTC"]).replace("Z","+00:00"))
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except (KeyError,ValueError,TypeError):
        return None

def parse_dfo_starters(html,date,games,diagnostics=None):
    """Exact game header, official NHL goalie ID, source's own starter label.

    A historical or adjacent-date card, line-combo goalie, or narrative goalie
    name cannot be upgraded to a starter. Unconfirmed is explicitly omitted.
    """
    diagnostics=diagnostics if diagnostics is not None else []
    if not html or not isinstance(html,str):
        return [],"EMPTY_SOURCE"
    parser=_Text()
    parser.feed(html)
    content="\n".join(v.strip() for v in "".join(parser.chunks).splitlines() if v.strip())
    try:
        day=datetime.strptime(date,"%Y-%m-%d")
    except ValueError:
        return [],"INVALID_SLATE_DATE"
    if (not re.search(r"\bNHL Starting Goalies\s*:\s*"+day.strftime("%A")+
           r",\s*"+day.strftime("%B")+r"\s+"+str(day.day)+r"\b",
           content,re.I)):
        return [],"SOURCE_DATE_UNVERIFIED"
    # Only source headings for games in the official schedule can define a
    # section. Match them in page order to avoid reading another game's goalie.
    headings=[]
    for game in games:
        away,home=(_club_name(game.get(k)) for k in ("away","home"))
        if not away or not home:
            diagnostics.append({"gameId":str(game.get("id")),"reason":"UNSUPPORTED_TEAM"})
            continue
        header=away+" at "+home
        for match in re.finditer(r"(?m)^\s*"+re.escape(header)+r"\s*$",content):
            headings.append((match.start(),match.end(),game))
    headings.sort()
    found=[]
    for i,(start,end,game) in enumerate(headings):
        stop=headings[i+1][0] if i+1<len(headings) else len(content)
        section=content[end:stop]
        game_id=str(game["id"])
        utc=_expected_utc(game)
        if (not utc or not re.search(re.escape(utc)+r"(?:\.\d+)?Z",section)):
            diagnostics.append({"gameId":game_id,"reason":"GAME_START_NOT_MATCHED"})
            continue
        # A goalie identity MUST be a standalone name immediately followed by
        # that person's reported starting status; prose and image alt are not
        # sufficient evidence.
        for team in (game["away"],game["home"]):
            roster=((game.get("rosters") or {}).get(team) or {}).get("data") or {}
            candidates=[]
            for goalie in roster.get("goalies") or []:
                name=str(goalie.get("name") or "")
                if len(_normalize(name))<6:continue
                pattern=r"(?m)^\s*"+re.escape(name)+r"\s*\n\s*(Confirmed|Likely|Projected|Unconfirmed)\s*(?:\n|$)"
                for match in re.finditer(pattern,section,re.I):
                    candidates.append((match.start(),goalie,match.group(1).title()))
            # Source lists away starter then home starter. A unique pair must
            # match the actual TWO official NHL roster teams in order.
            candidates.sort(key=lambda x:x[0])
            own=[x for x in candidates if str(x[1].get("id"))]
            if len(own)!=1:
                diagnostics.append({"gameId":game_id,"team":team,
                    "reason":"STARTER_NOT_UNIQUELY_OFFICIAL_ID_MATCHED",
                    "sourceMatches":len(own)})
                continue
            pos,goalie,label=own[0]
            all_positions=[]
            for other in (game["away"],game["home"]):
                other_roster=((game.get("rosters") or {}).get(other) or {}).get("data") or {}
                for g in other_roster.get("goalies") or []:
                    n=str(g.get("name") or "")
                    if not n:continue
                    for m in re.finditer(r"(?m)^\s*"+re.escape(n)+
                          r"\s*\n\s*(Confirmed|Likely|Projected|Unconfirmed)\s*(?:\n|$)",
                          section,re.I):
                        all_positions.append((m.start(),other,str(g.get("id"))))
            order=sorted(all_positions,key=lambda x:x[0])
            idx=0 if team==game["away"] else 1
            if len(order)!=2 or order[idx][0]!=pos or order[idx][1]!=team:
                diagnostics.append({"gameId":game_id,"team":team,
                    "reason":"TEAM_STARTER_ORDER_AMBIGUOUS"})
                continue
            if label=="Unconfirmed":
                diagnostics.append({"gameId":game_id,"team":team,
                    "reason":"SOURCE_STARTER_UNCONFIRMED_NO_PREFERRED_ID"})
                continue
            status=STARTER_LABELS.get(label)
            if not status:continue
            found.append({"gameId":game_id,"team":team,
                "goalieId":str(goalie["id"]),"goalieName":name,
                "status":status,"sourceLabel":label,
                "projectedPreferred":status=="EXPECTED",
                "identityMatched":True})
            diagnostics.append({"gameId":game_id,"team":team,
                "reason":"EXACT_DATED_NHL_ROSTER_STARTER_MATCH","status":status})
    return found,("MATCHED_DATED_STARTERS" if found else "NO_DATED_MATCHES")

async def collect_dfo_goalies(con,snapshot,date,stage):
    url=URL.format(date=date)
    diagnostics=[]
    try:
        async with httpx.AsyncClient(timeout=18,follow_redirects=True,
            headers={"User-Agent":"Mozilla/5.0 (compatible; NHLTrueBlender/1.0)"}) as client:
            response=await client.get(url)
            response.raise_for_status()
            html=response.text
    except (httpx.HTTPError,ValueError) as exc:
        return {"status":"SOURCE_UNAVAILABLE","source":url,
                "error":type(exc).__name__,
                "noStarterWasInferredFromFetchFailure":True}
    matches,status=parse_dfo_starters(html,date,snapshot.get("games",[]),diagnostics)
    observed=datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in matches:
        # Stable per-source name/id evidence. Never ingest team name only.
        digest=hashlib.sha256(
            f"{date}:{stage}:{row['gameId']}:{row['team']}:{row['goalieId']}:{row['sourceLabel']}".encode()
        ).hexdigest()[:14]
        ingest(con,{"evidence_id":f"dfo-slate-starter-{digest}",
            "slate_date":date,"stage":stage,"game_id":row["gameId"],
            "kind":"GOALIE_STARTER","source_url":url,
            "observed_at":observed,
            "payload":{"team":row["team"],"goalieId":row["goalieId"],
                "goalieName":row["goalieName"],"status":row["status"],
                "projectedPreferred":row["projectedPreferred"],
                "starterSourceStatus":"DAILY_FACEOFF_"+row["sourceLabel"].upper(),
                "sourceLabel":row["sourceLabel"],"identityMatched":True,
                "confirmedOnlyWhenSourceReportsConfirmed":True,
                "publishedAsOfSlateDate":date,
                "noSoleSourceGuaranteeOfFutureGoalieAppearance":True}})
    return {"status":status,"source":url,
        "matchedStarterIds":len(matches),
        "matchesByGame":{str(g["id"]):sum(x["gameId"]==str(g["id"]) for x in matches)
                         for g in snapshot.get("games",[])},
        "diagnostics":diagnostics,
        "originalSourceStatusPreserved":True,
        "noManualGoalieSelection":True}
