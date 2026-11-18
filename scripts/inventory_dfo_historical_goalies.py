"""Inventory Daily Faceoff's dated historical starting-goalie pages without using postgame sources."""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text=[];self.image_alt=[];self.times=[];self.meta=[]
        self.skip=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("script","style"):self.skip+=1
        if tag=="img" and a.get("alt"):self.image_alt.append(a["alt"])
        if tag=="time" and a.get("datetime"):self.times.append(a["datetime"])
        if tag=="meta" and a.get("content"):self.meta.append({"name":a.get("name") or a.get("property"),"content":a["content"]})
    def handle_endtag(self,tag):
        if tag in ("script","style") and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip and data and data.strip():self.text.append(" ".join(data.split()))


def fetch(day, outdir):
    url=f"https://www.dailyfaceoff.com/starting-goalies/{day}"
    request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; HistoricalNHLResearch/1.0)"})
    downloaded=datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            raw=response.read();status=response.status;final_url=response.geturl()
        parser=PageText();parser.feed(raw.decode("utf-8","replace"))
        text=parser.text
        statuses=[x for x in text if re.search(r"\b(Confirmed|Expected|Unconfirmed|Projected|Likely|Probable)\b",x,re.I)]
        matchups=[x for x in text if re.search(r"\b(at|@)\b",x,re.I) and len(x)<100]
        excerpts=[]
        for alt in parser.image_alt:
            if "Image:" not in alt:continue
            name=alt.split("Image:",1)[-1].strip()
            pos=next((i for i,x in enumerate(text) if name.lower() in x.lower()),None)
            excerpts.append({"goalieName":name,"nearbyText":text[max(0,pos-2):pos+6] if pos is not None else []})
        raw_path=outdir/f"{day}.html";raw_path.write_bytes(raw)
        return {
            "date":day,"url":final_url,"httpStatus":status,"downloadedAt":downloaded,
            "pageSha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
            "pageTitleOrMeta":parser.meta[:30],"pageTimestamps":sorted(set(parser.times)),
            "goalieImageNames":parser.image_alt,"goalieCardExcerpts":excerpts,
            "statusText":statuses[:100],"matchupText":matchups[:100],
            "visibleTextExcerpt":text[:120],
            "rawHtmlPath":str(raw_path),"availableAsDatedHistoricalPage":status==200,
        }
    except Exception as exc:
        return {"date":day,"url":url,"downloadedAt":downloaded,
                "availableAsDatedHistoricalPage":False,
                "errorType":type(exc).__name__,"error":str(exc)[:1000]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("manifest",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    manifest=json.loads(a.manifest.read_text())
    dates=sorted(manifest.get("scheduledDates") or [])
    rawdir=a.output.parent/"dfo_goalie_pages";rawdir.mkdir(parents=True,exist_ok=True)
    rows=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(fetch,day,rawdir) for day in dates]
        for future in as_completed(futures):rows.append(future.result())
    rows.sort(key=lambda x:x["date"])
    report={
        "source":"Daily Faceoff historical starting-goalie pages",
        "dateRange":[manifest["start"],manifest["end"]],
        "scheduledDatesChecked":len(dates),
        "accessibleDatedPages":sum(x.get("availableAsDatedHistoricalPage") is True for x in rows),
        "unavailableDates":[x["date"] for x in rows if not x.get("availableAsDatedHistoricalPage")],
        "pages":rows,
        "notUsedBySelector":True,
        "downloadTimeIsNotPagePublicationTime":True,
        "goalieNamesNeedIndependentNHLPlayerIdResolution":True,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="pages"},sort_keys=True))


if __name__=="__main__":main()
