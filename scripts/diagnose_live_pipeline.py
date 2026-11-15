"""Read-only live connector diagnostic; never awards G0 PASS or writes a Core."""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx

NHL="https://api-web.nhle.com/v1"
BTL="https://www.betweenthelineshockey.com/tonight.md"

def brief(value):
    if isinstance(value,dict):
        return {"keys":list(value.keys())[:40],
                "samples":{k:(v[:1] if isinstance(v,list) else
                               {"keys":list(v)[:16]} if isinstance(v,dict) else v)
                           for k,v in value.items()
                           if isinstance(v,list) and v or k in ("season","gameType")}}
    return {"type":type(value).__name__}

async def run():
    date=datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    async with httpx.AsyncClient(timeout=18,follow_redirects=True,headers={"User-Agent":"NHLTrueBlender/1.0","Accept":"application/json,text/markdown"}) as client:
        schedule=await client.get(f"{NHL}/score/{date}")
        print("OFFICIAL_SCHEDULE",schedule.status_code)
        schedule.raise_for_status()
        games=schedule.json().get("games",[])
        print("NHL_GAMES",len(games),"PLAYING",[(g["awayTeam"]["abbrev"],g["homeTeam"]["abbrev"]) for g in games])
        text=await client.get(BTL)
        print("BTL_STATUS",text.status_code,"BTL_FIRST_LINE",text.text.splitlines()[0] if text.text else "")
        from nhl_true_blender_engine.lineup_parser import parse_markdown
        parsed=parse_markdown(text.text) if text.status_code==200 else {}
        print("BTL_GOALIES",[(g["team"],g["name"],g["status"]) for g in parsed.get("goalies",[])][:20])
        teams=list(dict.fromkeys(t["abbrev"] for g in games for t in (g["awayTeam"],g["homeTeam"])))
        candidates=[]
        for team in teams[:2]:
            try:
                roster=await client.get(f"{NHL}/roster/{team}/current")
                print("NHL_ROSTER",team,roster.status_code,"CATEGORIES",list(roster.json())[:10] if roster.status_code==200 else None)
                roster.raise_for_status()
                data=roster.json()
                candidates.extend([("goalie",p["id"]) for p in data.get("goalies",[])[:1]])
                candidates.extend([("skater",p["id"]) for p in data.get("forwards",[])[:1]])
            except Exception as exc:
                print("ROSTER_ERROR",team,type(exc).__name__,str(exc)[:200])
        for kind,pid in candidates[:4]:
            path=f"edge/{'goalie' if kind=='goalie' else 'skater'}-shot-location-detail/{pid}/now"
            try:
                response=await client.get(f"{NHL}/{path}")
                print("EDGE_ENDPOINT",kind,pid,response.status_code)
                if response.status_code==200:
                    body=response.json()
                    print("EDGE_SCHEMA",kind,pid,json.dumps(brief(body),default=str)[:1600])
                else:
                    print("EDGE_MESSAGE",response.text[:250])
            except Exception as exc:
                print("EDGE_ERROR",kind,pid,type(exc).__name__,str(exc)[:240])

if __name__=="__main__":
    asyncio.run(run())
