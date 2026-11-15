"""Official NHL EDGE 2026-27 rink-area collector for every team roster skater and goalie.

These are shot ORIGIN zones, not the puck's impact location in the goal mouth.
Under no circumstances convert them into glove, blocker, or five-hole claims.
Only a separately verified goal-mouth source may certify anatomical G0/G5.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from .storage import record_evidence

ET=ZoneInfo("America/New_York")
GOALIE_KEYS=("shotsAgainst","saves","goalsAgainst","savePctg","savePctgPercentile")
SKATER_KEYS=("sog","goals","shootingPctg","sogPercentile","goalsPercentile")
FAMILY="NHL_EDGE_SHOT_ORIGIN_RINK_ONLY"

def _integer(value):
    return isinstance(value,int) and not isinstance(value,bool) and value>=0

def parse_edge(payload,kind,pid):
    """Accept only NHL's actual shotLocationDetails array; never invent a zone."""
    data=payload.get("data")
    if not isinstance(data,dict):
        raise ValueError("NHL EDGE response not a statistics object")
    player=data.get("player")
    if isinstance(player,dict) and player.get("id") is not None and str(player["id"])!=str(pid):
        raise ValueError("NHL EDGE result player ID mismatch")
    rows=data.get("shotLocationDetails")
    if not isinstance(rows,list) or not rows:
        raise ValueError("NHL EDGE has no shot location sample")
    keys=GOALIE_KEYS if kind=="goalie" else SKATER_KEYS
    normalized=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("area"),str):
            continue
        area=row["area"].strip()
        if not area:
            continue
        n={k:row.get(k) for k in keys}
        shots=n.get("shotsAgainst" if kind=="goalie" else "sog")
        goals=n.get("goalsAgainst" if kind=="goalie" else "goals")
        if not (_integer(shots) and _integer(goals) and goals<=shots):
            continue
        if kind=="goalie":
            saves=n["saves"]
            if not _integer(saves) or saves+goals!=shots:
                continue
        else:
            saves=None
        normalized.append({"area":area,**n})
    if not normalized:
        raise ValueError("NHL EDGE no source-consistent shot-zone records")
    return {
        "playerId":str(pid),
        "kind":kind.upper(),
        "scope":FAMILY,
        "rinkZoneRows":normalized,
        "shotLocationTotals":data.get("shotLocationTotals",[]),
        "anatomicalGloveBlockerFiveHoleVerified":False,
        "sourceType":"NHL_EDGE_OFFICIAL_RINK_SHOT_ORIGIN",
        "note":"Shot origin areas are not a goal-mouth impact map",
    }

async def collect_edge(client,con,snapshot,date,stage,concurrency=6):
    """Analyze ALL current roster identities, including depth and D; never pick stars first.

    For historical replay, only fetch if the slate date is TODAY in Eastern time.
    NHL EDGE current-season stats would otherwise leak games after the backtest.
    """
    today=datetime.now(ET).date().isoformat()
    if date!=today:
        return {"status":"NO_HISTORICAL_EDGE_SNAPSHOT_AS_OF","slateDate":date,
                "scope":FAMILY,"anatomicalClaimCertified":False}
    jobs={}
    for g in snapshot.get("games",[]):
        for team in (g["away"],g["home"]):
            roster=(g.get("rosters",{}).get(team) or {}).get("data",{})
            for p in roster.get("goalies",[]):
                if p.get("id"):
                    jobs[("goalie",str(p["id"]))]=None
            for p in roster.get("players",[]):
                if p.get("id"):
                    jobs[("skater",str(p["id"]))]=None
    sem=asyncio.Semaphore(concurrency)
    async def one(kind,pid):
        async with sem:
            try:
                payload=await client.get(f"edge/{kind}-shot-location-detail/{pid}/now")
                proof=parse_edge(payload,kind,pid)
                return (kind,pid,payload,proof,None)
            except Exception as exc:
                return (kind,pid,None,None,f"{type(exc).__name__}: {exc}")
    results=await asyncio.gather(*(one(*key) for key in jobs))
    successes={(kind,pid):(payload,proof) for kind,pid,payload,proof,error in results if proof}
    for g in snapshot.get("games",[]):
        for team in (g["away"],g["home"]):
            roster=(g.get("rosters",{}).get(team) or {}).get("data",{})
            members=[("goalie",str(p["id"])) for p in roster.get("goalies",[]) if p.get("id")]
            members += [("skater",str(p["id"])) for p in roster.get("players",[]) if p.get("id")]
            for kind,pid in members:
                if (kind,pid) not in successes:
                    continue
                raw,proof=successes[(kind,pid)]
                compact=json.dumps(proof,sort_keys=True,separators=(",",":"))
                evidence_id=f"edge-{date}-{stage}-{g['id']}-{kind}-{pid}-"+hashlib.sha256(compact.encode()).hexdigest()[:12]
                record_evidence(con,{
                    "evidence_id":evidence_id,"slate_date":date,"stage":stage,
                    "game_id":str(g["id"]),"player_id":pid,
                    "kind":"NHL_EDGE_GOALIE_RINK_ORIGIN" if kind=="goalie" else "NHL_EDGE_SKATER_RINK_ORIGIN",
                    "source_url":raw["url"],"observed_at":raw["observedAt"],"payload":proof
                })
    failed=[{"kind":k,"playerId":p,"reason":err[:240]}
            for k,p,payload,proof,err in results if err]
    return {"status":"EVIDENCE_COLLECTED","scope":FAMILY,
            "allCurrentRosterIdentitiesChecked":len(jobs),
            "goalieRinkProfiles":sum(k=="goalie" for k,p in successes),
            "skaterRinkProfiles":sum(k=="skater" for k,p in successes),
            "sourceFailures":failed[:50],"totalFailed":len(failed),
            "anatomicalClaimCertified":False,
            "source":"https://api-web.nhle.com/v1/edge/",
            "doesNotReplaceGoalMouthScout":True}


def review_g0_goalie_origins(con,snapshot,date,stage):
    """Compare both opponent goalies using only observed NHL EDGE shot-origin areas.

    For G0 research, not a new goalie starter claim or anatomical G0 pass.
    A league-median percentile is descriptive: no scored/weighted side selection.
    """
    import json
    output=[]
    for game in snapshot.get("games",[]):
        directions=[]
        for attacker,defender in ((game["away"],game["home"]),(game["home"],game["away"])):
            branches=game.get("goalies",{}).get(defender,[])
            branch_rows=[]
            for branch in branches:
                data=branch.get("data") or {}
                if data.get("status") not in ("PROJECTED","EXPECTED","CONFIRMED"):
                    continue
                if stage=="CONFIRMED" and data.get("status")!="CONFIRMED":
                    continue
                gid=str(data.get("goalieId") or "")
                source=con.execute("""SELECT payload,source_url,observed_at FROM evidence
                    WHERE slate_date=? AND stage=? AND game_id=? AND player_id=?
                    AND kind='NHL_EDGE_GOALIE_RINK_ORIGIN'
                    ORDER BY observed_at DESC LIMIT 1""",(date,stage,str(game["id"]),gid)).fetchone()
                if not source:
                    branch_rows.append({"goalieId":gid,"starterStatus":data["status"],
                                        "zoneProfileFound":False})
                    continue
                profile=json.loads(source["payload"])
                rows=[{"area":z["area"],"shotsAgainst":z["shotsAgainst"],
                       "goalsAgainst":z["goalsAgainst"],
                       "savePctg":z.get("savePctg"),
                       "savePctgPercentile":z.get("savePctgPercentile")}
                      for z in profile["rinkZoneRows"]
                      if z["shotsAgainst"]>=30 and
                         isinstance(z.get("savePctgPercentile"),(int,float))]
                branch_rows.append({"goalieId":gid,"starterStatus":data["status"],
                                    "zoneProfileFound":True,
                                    "rinkShotOriginAreaRows":rows,
                                    "sourceUrl":source["source_url"]})
            directions.append({"attacker":attacker,"defender":defender,
                               "goalieBranches":branch_rows})
        output.append({"gameId":str(game["id"]),"matchup":game["away"]+"@"+game["home"],
                       "directions":directions,"anatomicalWeaknessCertified":False,
                       "status":"RINK_SHOT_ORIGIN_RESEARCH_ONLY"})
    return output
