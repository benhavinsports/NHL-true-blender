"""Inspect the public 5V5 Hockey historical-line archive interface for its data endpoint."""
import argparse,hashlib,json,re,urllib.request
from datetime import datetime,timezone
from html.parser import HTMLParser
from pathlib import Path

class Probe(HTMLParser):
    def __init__(self):
        super().__init__();self.scripts=[];self.forms=[];self.inputs=[];self.text=[];self.inline=[]
        self.in_script=False;self.current_script=""
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="script":
            self.in_script=True;self.current_script=""
            if a.get("src"):self.scripts.append(a["src"])
        if tag=="form":self.forms.append({"attrs":a})
        if tag=="input":self.inputs.append(a)
        if tag=="button":self.inputs.append({"tag":"button",**a})
    def handle_endtag(self,tag):
        if tag=="script":
            if self.current_script:self.inline.append(self.current_script[:20000])
            self.in_script=False;self.current_script=""
    def handle_data(self,data):
        if self.in_script:self.current_script+=data
        elif data.strip():self.text.append(" ".join(data.split()))

def main():
    p=argparse.ArgumentParser();p.add_argument("output",type=Path);a=p.parse_args()
    url="https://5v5hockey.com/hockey/historical-line-matchups/"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    downloaded=datetime.now(timezone.utc).isoformat(timespec="seconds")
    with urllib.request.urlopen(req,timeout=30) as r:
        raw=r.read();status=r.status;final=r.geturl()
    html=raw.decode("utf-8","replace");probe=Probe();probe.feed(html)
    patterns=r"(?:/wp-json/|admin-ajax\\.php|api/|historical[^\\\"' ]*|line-match[^\\\"' ]*|ajax[^\\\"' ]*)"
    hits=sorted(set(re.findall(patterns,html,re.I)))
    script_hits=[]
    for script in probe.inline:
        script_hits += re.findall(patterns,script,re.I)
    report={"url":final,"httpStatus":status,"downloadedAt":downloaded,
        "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
        "scriptSources":probe.scripts,"forms":probe.forms,"inputs":probe.inputs,
        "endpointLikeStrings":hits,"inlineScriptEndpointStrings":sorted(set(script_hits)),
        "visibleText":probe.text[:180],"htmlPath":str(a.output.with_suffix(".html"))}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    a.output.with_suffix(".html").write_bytes(raw)
    print(json.dumps({k:v for k,v in report.items() if k not in ("forms","inputs","visibleText")},sort_keys=True))
if __name__=="__main__":main()
