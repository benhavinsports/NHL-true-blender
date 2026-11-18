"""Inventory and parse dated Daily Faceoff historical starting-goalie reports."""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

TEAM_ABBREV = {
    "Anaheim Ducks":"ANA","Boston Bruins":"BOS","Buffalo Sabres":"BUF",
    "Calgary Flames":"CGY","Carolina Hurricanes":"CAR","Chicago Blackhawks":"CHI",
    "Colorado Avalanche":"COL","Columbus Blue Jackets":"CBJ","Dallas Stars":"DAL",
    "Detroit Red Wings":"DET","Edmonton Oilers":"EDM","Florida Panthers":"FLA",
    "Los Angeles Kings":"LAK","Minnesota Wild":"MIN","Montreal Canadiens":"MTL",
    "Nashville Predators":"NSH","New Jersey Devils":"NJD","New York Islanders":"NYI",
    "New York Rangers":"NYR","Ottawa Senators":"OTT","Philadelphia Flyers":"PHI",
    "Pittsburgh Penguins":"PIT","San Jose Sharks":"SJS","Seattle Kraken":"SEA",
    "St. Louis Blues":"STL","St Louis Blues":"STL","Tampa Bay Lightning":"TBL","Toronto Maple Leafs":"TOR",
    "Utah Mammoth":"UTA","Vancouver Canucks":"VAN","Vegas Golden Knights":"VGK",
    "Washington Capitals":"WSH","Winnipeg Jets":"WPG",
}
STATUSES={"Confirmed","Unconfirmed","Expected","Projected","Likely","Probable"}
ISO_RE=re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text=[];self.image_alt=[];self.image_src=[];self.times=[];self.meta=[]
        self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("script","style"):self.skip+=1
        if tag=="img" and a.get("alt"):
            self.image_alt.append(a["alt"])
            self.image_src.append({"alt":a["alt"],"src":a.get("src")})
        if tag=="time" and a.get("datetime"):self.times.append(a["datetime"])
        if tag=="meta" and a.get("content"):
            self.meta.append({"name":a.get("name") or a.get("property"),"content":a["content"]})
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip and data and data.strip():self.text.append(" ".join(data.split()))

def _parse_goalie_cards(parser):
    text=parser.text
    generic={"logo","starting goalies","line combination","bet365","puckpedia","daily faceoff"}
    image_by_name={_normalize_name(x["alt"].replace("Image:","").strip()):x.get("src")
                   for x in parser.image_src}
    cards=[]
    seen=set()
    for i in range(1,len(text)-1):
        status=text[i]
        updated=text[i+1]
        if status not in STATUSES or not ISO_RE.match(updated):
            continue
        name=text[i-1].strip()
        if not name or name.lower() in generic or _normalize_name(name) in seen:
            continue
        # DFO's historical card order is away goalie then home goalie for
        # each matchup; each card has a status immediately followed by its
        # report-update timestamp.
        cards.append({"name":name,"status":status,"reportUpdatedAt":updated,
                      "imageUrl":image_by_name.get(_normalize_name(name))})
        seen.add(_normalize_name(name))
    return cards

def _parse_matchups(text,schedule_games):
    matchups=[]
    for i in range(len(text)-3):
        if text[i+1].lower()=="at" and ISO_RE.match(text[i+3]):
            away_name,home_name=text[i],text[i+2]
            away,home=TEAM_ABBREV.get(away_name),TEAM_ABBREV.get(home_name)
            game=next((g for g in schedule_games if g.get("away")==away and g.get("home")==home),None)
            matchups.append({"awayName":away_name,"homeName":home_name,
                "away":away,"home":home,"startTimeUTC":text[i+3],
                "gameId":game.get("gameId") if game else None,
                "officialScheduleMatch":game is not None})
    return matchups

def _before(a,b):
    try:
        return datetime.fromisoformat(a.replace("Z","+00:00")) <= datetime.fromisoformat(b.replace("Z","+00:00"))
    except (AttributeError,ValueError):
        return None

def _official_game_start(game):
    """Accept the official calendar's startUTC and the legacy startTimeUTC alias."""
    value=game.get("startTimeUTC") or game.get("startUTC")
    if not isinstance(value,str):
        return None
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None

def _normalize_name(value):
    return "".join(ch for ch in unicodedata.normalize("NFKD",value or "")
                   if not unicodedata.combining(ch)).casefold().strip()

def _resolve_nhl_player(name):
    url="https://search.d3.nhle.com/api/v1/search/player?"+urlencode({
        "culture":"en-us","limit":20,"q":name})
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req,timeout=20) as response:
            payload=json.loads(response.read().decode("utf-8","replace"))
        if isinstance(payload,dict):
            payload=payload.get("suggestions") or payload.get("players") or []
        exact=[x for x in payload if _normalize_name(x.get("name") or x.get("fullName"))==_normalize_name(name)]
        goalies=[x for x in exact if (x.get("positionCode") or x.get("position")) in ("G","Goalie","Goalkeeper")]
        if len(goalies)==1:
            item=goalies[0]
            return {"playerId":str(item.get("playerId") or item.get("id")),
                    "officialName":item.get("name") or item.get("fullName"),
                    "positionCode":item.get("positionCode") or item.get("position"),
                    "currentTeamAbbrev":item.get("teamAbbrev"),
                    "status":"EXACT_OFFICIAL_NHL_NAME_AND_GOALIE_MATCH","sourceUrl":url}
        return {"status":"NO_UNIQUE_EXACT_NHL_GOALIE_MATCH","matchCount":len(exact),
                "goalieMatchCount":len(goalies),"sourceUrl":url}
    except Exception as exc:
        return {"status":"OFFICIAL_NHL_PLAYER_SEARCH_UNAVAILABLE",
                "errorType":type(exc).__name__,"error":str(exc)[:500],"sourceUrl":url}

def fetch(day,outdir,manifest_schedule):
    url=f"https://www.dailyfaceoff.com/starting-goalies/{day}"
    request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; HistoricalNHLResearch/1.0)"})
    downloaded=datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            raw=response.read();status=response.status;final_url=response.geturl()
        parser=PageText();parser.feed(raw.decode("utf-8","replace"))
        schedule_games=((manifest_schedule.get(day) or {}).get("games") or [])
        start_times=[_official_game_start(g) for g in schedule_games]\n        start_times=[x for x in start_times if x is not None]
        slate_cutoff=(min(start_times)-
                      timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00","Z") if start_times else None
        cards=_parse_goalie_cards(parser)
        for goalie in cards:
            image_team=re.search(r"[_-]([A-Z]{3})-",goalie.get("imageUrl") or "")
            goalie["imageTeamAbbrev"]=image_team.group(1) if image_team else None
            goalie["reportUpdatedBeforeSlateCutoff"]=_before(goalie.get("reportUpdatedAt"),slate_cutoff) if slate_cutoff else None
        matchups=_parse_matchups(parser.text,schedule_games)
        games=[]
        for idx,match in enumerate(matchups):
            pair=cards[idx*2:idx*2+2]
            game={**match,"awayGoalie":pair[0] if len(pair)>0 else None,
                  "homeGoalie":pair[1] if len(pair)>1 else None,
                  "goaliePairComplete":len(pair)==2}
            for side,team in (("awayGoalie",match.get("away")),("homeGoalie",match.get("home"))):
                goalie=game[side]
                if goalie:
                    goalie["assignedTeam"]=team
                    goalie["imageTeamAbbrevMatchesAssignedTeam"]=(
                        goalie.get("imageTeamAbbrev")==team if goalie.get("imageTeamAbbrev") else None)
                    goalie["reportUpdatedBeforeGameStart"]=_before(goalie.get("reportUpdatedAt"),match["startTimeUTC"])
            game["pairTeamIdentityMatches"]=all(
                game[side].get("imageTeamAbbrevMatchesAssignedTeam") is True
                for side in ("awayGoalie","homeGoalie") if game.get(side) and game[side].get("imageTeamAbbrev"))
            games.append(game)
        raw_path=outdir/f"{day}.html";raw_path.write_bytes(raw)
        statuses=[x for x in parser.text if x in STATUSES]
        return {
            "date":day,"url":final_url,"httpStatus":status,"downloadedAt":downloaded,
            "slateCutoff":slate_cutoff,
            "pageSha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
            "pageTitleOrMeta":parser.meta[:30],"pageTimestamps":sorted(set(parser.times)),
            "goalieCards":cards,"matchupRecords":matchups,"games":games,
            "goalieImageNames":parser.image_alt,"goalieImageSources":parser.image_src,
            "statusText":statuses,"visibleTextExcerpt":parser.text[:160],
            "rawHtmlPath":str(raw_path),"availableAsDatedHistoricalPage":status==200,
            "completeGamePairs":sum(x["goaliePairComplete"] for x in games),
            "matchedOfficialGames":sum(x["officialScheduleMatch"] for x in games),
        }
    except Exception as exc:
        return {"date":day,"url":url,"downloadedAt":downloaded,
                "availableAsDatedHistoricalPage":False,
                "errorType":type(exc).__name__,"error":str(exc)[:1000]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest",type=Path);p.add_argument("output",type=Path)
    a=p.parse_args();manifest=json.loads(a.manifest.read_text())
    dates=sorted(manifest.get("scheduledDates") or [])
    rawdir=a.output.parent/"dfo_goalie_pages";rawdir.mkdir(parents=True,exist_ok=True)
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(fetch,day,rawdir,manifest.get("officialSchedule") or {}) for day in dates]
        for future in as_completed(futures):rows.append(future.result())
    rows.sort(key=lambda x:x["date"])
    unique_names=sorted({g["name"] for page in rows for g in page.get("goalieCards",[])})
    resolutions={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(_resolve_nhl_player,name):name for name in unique_names}
        for future in as_completed(futures):
            resolutions[futures[future]]=future.result()
    for page in rows:
        for goalie in page.get("goalieCards",[]):
            goalie["nhlIdentityResolution"]=resolutions.get(goalie["name"])
            goalie["nhlPlayerId"]=(goalie["nhlIdentityResolution"] or {}).get("playerId")
        for game in page.get("games",[]):
            for side in ("awayGoalie","homeGoalie"):
                goalie=game.get(side)
                if goalie:
                    goalie["nhlIdentityResolution"]=resolutions.get(goalie["name"])
    report={
        "source":"Daily Faceoff dated historical starting-goalie pages",
        "dateRange":[manifest["start"],manifest["end"]],
        "scheduledDatesChecked":len(dates),
        "accessibleDatedPages":sum(x.get("availableAsDatedHistoricalPage") is True for x in rows),
        "completeGamePairs":sum(x.get("completeGamePairs",0) for x in rows),
        "officialGamesMatched":sum(x.get("matchedOfficialGames",0) for x in rows),
        "goalieCardsParsed":sum(len(x.get("goalieCards",[])) for x in rows),
        "goaliePlayerIdsResolved":sum(x.get("status")=="EXACT_OFFICIAL_NHL_NAME_AND_GOALIE_MATCH" for x in resolutions.values()),
        "uniqueGoalieNames":len(unique_names),
        "unresolvedGoalieNames":{k:v for k,v in resolutions.items() if v.get("status")!="EXACT_OFFICIAL_NHL_NAME_AND_GOALIE_MATCH"},
        "unavailableDates":[x["date"] for x in rows if not x.get("availableAsDatedHistoricalPage")],
        "pages":rows,"notUsedBySelector":True,
        "downloadTimeIsNotPagePublicationTime":True,
        "perGoalieReportUpdateTimeParsed":True,
        "goalieNamesNeedIndependentNHLPlayerIdResolution":True,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="pages"},sort_keys=True))
if __name__=="__main__":main()
