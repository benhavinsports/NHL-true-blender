"""Collect NHL goal-event puck tracking for historical scoring-route research.

Raw goal sprites are source data; x/y rink positions are NOT anatomical
glove/blocker/five-hole proof. Never promote them to GOALIE_PROFILE.
"""
from __future__ import annotations
import asyncio, json
from pathlib import Path
import httpx

async def collect_goal_sprites(client, snapshot, slate_date, out_dir="runs/goal_tracking", max_games_per_team=3, max_goals=80):
    season_start=int(slate_date[:4]) if int(slate_date[5:7])>=9 else int(slate_date[:4])-1
    season=f"{season_start}{season_start+1}"
    teams={t for g in snapshot["games"] for t in (g["away"],g["home"])}
    games={}
    for team in sorted(teams):
        try:
            payload=await client.get(f"club-schedule-season/{team}/{season}")
            past=[g for g in payload["data"].get("games",[]) if
                  g.get("gameDate","9999")<slate_date and g.get("gameState") in ("OFF","FINAL")]
            for game in past[-max_games_per_team:]:
                games[str(game["id"])]=game["gameDate"]
        except Exception:
            continue
    target=[]
    for gid,played in games.items():
        try:
            pbp=await client.play_by_play(gid)
            for play in pbp["data"].get("plays",[]):
                if play.get("typeDescKey")!="goal":continue
                if (play.get("periodDescriptor") or {}).get("periodType")=="SO":continue
                event=play.get("eventId")
                scorer=(play.get("details") or {}).get("scoringPlayerId")
                if event is not None and scorer is not None:
                    target.append((gid,played,str(event),str(scorer)))
        except Exception:
            continue
    root=Path(out_dir)/slate_date
    root.mkdir(parents=True,exist_ok=True)
    retrieved=0; missing=0
    async with httpx.AsyncClient(timeout=18,follow_redirects=True,
             headers={"Referer":"https://www.nhl.com/","User-Agent":"Mozilla/5.0"}) as http:
        for gid,played,event,scorer in target[:max_goals]:
            path=root/f"{gid}_ev{event}.json"
            if path.exists():
                retrieved+=1
                continue
            url=f"https://wsr.nhle.com/sprites/{season}/{gid}/ev{event}.json"
            try:
                # Resolve the league-provided replay URL rather than assuming its path.
                metadata=await client.get(f"ppt-replay/{gid}/{event}")
                goal=metadata["data"].get("goal") or {}
                published=goal.get("pptReplayUrl") or metadata["data"].get("pptReplayUrl")
                if not published or not published.startswith("https://wsr.nhle.com/sprites/"):
                    raise ValueError("NHL replay metadata lacks a trusted sprite URL")
                url=published
                response=await http.get(url)
                response.raise_for_status()
                payload=response.json()
                if not isinstance(payload,(list,dict)) or not payload:
                    raise ValueError("Empty or malformed tracking payload")
                path.write_text(json.dumps({"gameId":gid,"eventId":event,
                    "scorerId":scorer,"playedDate":played,"sourceUrl":url,
                    "tracking":payload},separators=(",",":")),encoding="utf-8")
                retrieved+=1
            except (httpx.HTTPError,ValueError):
                missing+=1
            await asyncio.sleep(.25)
    return {"historicalGames":len(games),"goalEvents":len(target),
            "requested":min(len(target),max_goals),"retrieved":retrieved,
            "missingOrUnavailable":missing,"directory":str(root),
            "anatomicalWeaknessInferred":False,
            "use":"historical goal-route research; no automatic G0 weakness assertion"}
