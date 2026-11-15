"""Multi-source research collector with provenance and bounded retry.

Independent lineup pages are kept as source documents. Their text is never
silently promoted to confirmed player/goalie data without structured identity
matching and status evidence.
"""
from __future__ import annotations
import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import quote
import httpx
from .storage import record_evidence

SOURCES = {
    "dailyfaceoff_lines": "https://www.dailyfaceoff.com/teams/{slug}/line-combinations/",
    "dailyfaceoff_goalies": "https://www.dailyfaceoff.com/starting-goalies",
    "nhl_team_news": "https://www.nhl.com/{slug}/news",
    "espn_injuries": "https://www.espn.com/nhl/injuries",
}
TEAM_SLUGS = {
 "ANA":"anaheim-ducks","BOS":"boston-bruins","BUF":"buffalo-sabres",
 "CAR":"carolina-hurricanes","CBJ":"columbus-blue-jackets",
 "CGY":"calgary-flames","CHI":"chicago-blackhawks",
 "COL":"colorado-avalanche","DAL":"dallas-stars",
 "DET":"detroit-red-wings","EDM":"edmonton-oilers",
 "FLA":"florida-panthers","LAK":"los-angeles-kings",
 "MIN":"minnesota-wild","MTL":"montreal-canadiens",
 "NJD":"new-jersey-devils","NSH":"nashville-predators",
 "NYI":"new-york-islanders","NYR":"new-york-rangers",
 "OTT":"ottawa-senators","PHI":"philadelphia-flyers",
 "PIT":"pittsburgh-penguins","SEA":"seattle-kraken",
 "SJS":"san-jose-sharks","STL":"st-louis-blues",
 "TBL":"tampa-bay-lightning","TOR":"toronto-maple-leafs",
 "UTA":"utah-mammoth","VAN":"vancouver-canucks",
 "VGK":"vegas-golden-knights","WPG":"winnipeg-jets",
 "WSH":"washington-capitals"
}
def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

async def fetch_source(client, url, attempts=3):
    errors = []
    for attempt in range(attempts):
        try:
            r = await client.get(url, timeout=18, follow_redirects=True)
            r.raise_for_status()
            html = r.text
            if len(html) < 100:
                raise ValueError("Empty source document")
            title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I|re.S)
            return {"url": str(r.url), "observedAt": timestamp(),
                    "title": re.sub(r"<[^>]*>", "", title.group(1)).strip() if title else "",
                    "bytes": len(html), "status": "FETCHED_UNPARSED",
                    "note": "Source retrieval alone is not confirmation of lineup or goalie."}
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(str(exc))
            if attempt + 1 < attempts:
                await asyncio.sleep(0.8 * (attempt + 1))
    return {"url": url, "observedAt": timestamp(),
            "status": "FETCH_FAILED", "errors": errors}

async def collect_secondary(con, snapshot, date, stage):
    teams = sorted({t for g in snapshot["games"] for t in (g["home"], g["away"])})
    urls = [(f"dailyfaceoff:{team}", SOURCES["dailyfaceoff_lines"].format(slug=TEAM_SLUGS[team]))
            for team in teams if team in TEAM_SLUGS]
    urls += [("dailyfaceoff:goalies", SOURCES["dailyfaceoff_goalies"]),
             ("espn:injuries", SOURCES["espn_injuries"])]
    semaphore = asyncio.Semaphore(4)
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0 (compatible; NHLTrueBlenderResearch/1.0)"}) as client:
        async def one(name, url):
            async with semaphore:
                return name, await fetch_source(client, url)
        results = await asyncio.gather(*(one(name, url) for name, url in urls))
    for name, result in results:
        record_evidence(con, {
            "evidence_id": f"source-research-{date}-{stage}-{name}-{result['observedAt']}",
            "slate_date": date, "stage": stage, "kind": "SOURCE_RESEARCH",
            "source_url": result["url"], "observed_at": result["observedAt"],
            "payload": {"name": name, **result}
        })
    return {"attempted": len(results),
            "fetched": sum(x["status"] == "FETCHED_UNPARSED" for _,x in results),
            "sources": [{"name": name, **r} for name,r in results]}
