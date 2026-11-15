"""Postgame grade from official NHL boxscore goals, never from projected picks."""
import json
from pathlib import Path
from nhl_data import get_schedule, get_bundle

def grade_slate(date, state_dir="state"):
    path = Path(state_dir) / f"authoritative_core_{date}.json"
    if not path.exists():
        return {"status": "NO_AUTHORITATIVE_CARD", "slateDate": date}
    card = json.loads(path.read_text(encoding="utf-8"))
    picks = card.get("core") or []
    if len(picks) not in (2, 3):
        return {"status": "INVALID_CARD", "slateDate": date}
    games = {str(g.get("gameId")): g for g in get_schedule(date)}
    outcomes = []
    for pick in picks:
        gid = str(pick.get("gameId"))
        game = games.get(gid)
        if not game:
            return {"status": "WAITING_FOR_OFFICIAL_GAME", "gameId": gid, "slateDate": date}
        if str(game.get("gameState", "")).upper() not in ("OFF", "FINAL"):
            return {"status": "WAITING_FOR_FINAL", "gameId": gid, "slateDate": date}
        bundle = get_bundle(game)
        box = bundle.get("boxscore") or {}
        pbg = box.get("playerByGameStats") or {}
        player_id = str(pick.get("playerId"))
        goals = None
        for side in ("homeTeam", "awayTeam"):
            for group in ("forwards", "defense"):
                for p in (pbg.get(side) or {}).get(group, []) or []:
                    if str(p.get("playerId") or p.get("id")) == player_id:
                        goals = p.get("goals")
        if goals is None:
            return {"status": "WAITING_FOR_OFFICIAL_PLAYER_STATS", "gameId": gid, "playerId": player_id}
        outcomes.append({"gameId": gid, "playerId": player_id, "goals": int(goals), "hit": int(goals) > 0})
    result = {"slateDate": date, "status": "GRADED", "result": "WIN" if all(x["hit"] for x in outcomes) else "LOSS",
              "hits": sum(x["hit"] for x in outcomes), "legs": len(outcomes),
              "players": outcomes, "source": "NHL official boxscore"}
    out = Path(state_dir) / f"grade_{date}.json"
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8"))
        if existing != result:
            return {"status": "GRADE_CONFLICT_REQUIRES_AUDIT", "existing": existing, "new": result}
    else:
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
