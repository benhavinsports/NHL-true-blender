"""Inventory and parse dated Daily Faceoff historical starting-goalie reports."""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
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
    "St. Louis Blues":"STL","Tampa Bay Lightning":"TBL","Toronto Maple Leafs":"TOR",
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
    cards=[]
    seen=set()
    for img in parser.image_src:
        name=img["alt"].replace("Image:","").strip()
        if not name or name.lower() in generic or name.lower().startswith("bet365") or name in seen:
            continue
        positions=[i for i,x in enumerate(text) if x.lower()==name.lower()]
        for pos in positions:
            status=text[pos+1] if pos+1<len(text) else None
            updated=text[pos+2] if pos+2<len(text) else None
            if status in STATUSES:
                cards.append({"name":name,"status":status,
                              "reportUpdatedAt":updated if isinstance(updated,str) and ISO_RE.match(updated) else None,
                              "imageUrl":img.get("src")})
                seen.add(name)
                break
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

def fetch(day,outdir,manifest_schedule):
    url=f"https://www.dailyfaceoff.com/starting-goalies/{day}"
    request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; HistoricalNHLResearch/1.0)"})
    downloaded=datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            raw=response.read();status=response.status;final_url=response.geturl()
        parser=PageText();parser.feed(raw.decode("utf-8","replace"))
        schedule_games=((manifest_schedule.get(day) or {}).get("games") or [])
        cards=_parse_goalie_cards(parser)
        matchups=_parse_matchups(parser.text,schedule_games)
        games=[]
        for idx,match in enumerate(matchups):
            pair=cards[idx*2:idx*2+2]
            game={**match,"awayGoalie":pair[0] if len(pair)>0 else None,
                  "homeGoalie":pair[1] if len(pair)>1 else None,
                  "goaliePairComplete":len(pair)==2}
            for side in ("awayGoalie","homeGoalie"):
                goalie=game[side]
                if goalie:
                    goalie["reportUpdatedBeforeGameStart"]=_before(goalie.get("reportUpdatedAt"),match["startTimeUTC"])
            games.append(game)
        raw_path=outdir/f"{day}.html";raw_path.write_bytes(raw)
        statuses=[x for x in parser.text if x in STATUSES]
        return {
            "date":day,"url":final_url,"httpStatus":status,"downloadedAt":downloaded,
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
    report={
        "source":"Daily Faceoff dated historical starting-goalie pages",
        "dateRange":[manifest["start"],manifest["end"]],
        "scheduledDatesChecked":len(dates),
        "accessibleDatedPages":sum(x.get("availableAsDatedHistoricalPage") is True for x in rows),
        "completeGamePairs":sum(x.get("completeGamePairs",0) for x in rows),
        "officialGamesMatched":sum(x.get("matchedOfficialGames",0) for x in rows),
        "goalieCardsParsed":sum(len(x.get("goalieCards",[])) for x in rows),
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
