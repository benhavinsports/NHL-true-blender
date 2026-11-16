"""Import user-supplied MoneyPuck season CSV snapshots as scoped, auditable evidence.

Never infer anatomical goalie weakness from danger tiers. CSV aggregates have no
per-game chronology; caller must provide a verified export as-of date.
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .enrichment import ingest

def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))

def _num(row, key):
    try:
        return float(row[key])
    except (ValueError, KeyError, TypeError):
        return 0.0

def _immutable_receipt_id(base, payload):
    # An upstream CSV can be updated repeatedly during the SAME slate.
    # A fixed (date,stage,player,kind) ID caused immutable receipt
    # conflicts on every second run when MoneyPuck changed one statistic.
    # Content-addressed revisions retain ALL earlier source observations,
    # while identical replays safely reuse the exact evidence receipt.
    blob=json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False)
    digest=hashlib.sha256(blob.encode('utf-8')).hexdigest()[:20]
    return f"{base}-{digest}"

def import_moneypuck(con, snapshot, slate_date, stage, directory, export_asof):
    if not export_asof or export_asof != slate_date:
        raise ValueError("MoneyPuck export as-of date must be verified and no later than slate")
    data = {name: _read(Path(directory)/f"{name}.csv")
            for name in ("goalies","skaters","lines","teams")}
    observed = datetime.now(timezone.utc).isoformat()
    imported = {"PLAYER_PRESSURE":0,"PLAYER_FINISH_CREDIT":0,
                "TEAM_COVERAGE":0,"GOALIE_STATISTICS":0}
    seasons={str(r.get("season")) for rows in data.values() for r in rows}
    expected_season=str(int(slate_date[:4]) if int(slate_date[5:7])>=9 else int(slate_date[:4])-1)
    if seasons!={expected_season}:
        raise ValueError(f"MoneyPuck season mismatch: {seasons}; expected {expected_season}")
    goalies = {(str(r["playerId"]),r["team"]):r for r in data["goalies"]
               if r["situation"]=="all"}
    skaters = {str(r["playerId"]):r for r in data["skaters"]
               if r["situation"]=="all"}
    teams = {r["team"]:r for r in data["teams"] if r["situation"]=="5on5"}
    for game in snapshot["games"]:
        for team in (game["away"],game["home"]):
            opponent = game["home"] if team==game["away"] else game["away"]
            t = teams.get(opponent)
            if t:
                payload = {"attackingTeam":team,"defendingTeam":opponent,
                           "highDangerShotsAgainst":_num(t,"highDangerShotsAgainst"),
                           "highDangerGoalsAgainst":_num(t,"highDangerGoalsAgainst"),
                           "mediumDangerShotsAgainst":_num(t,"mediumDangerShotsAgainst"),
                           "lowDangerShotsAgainst":_num(t,"lowDangerShotsAgainst"),
                           "evidenceType":"HISTORICAL_TEAM_DANGER_AGGREGATES",
                           "greenWeakZones":[],"redStrongZones":[],
                           "noAnatomicalZoneInference":True}
                ingest(con,{"evidence_id":_immutable_receipt_id(
                    f"mp-team-{slate_date}-{stage}-{game['id']}-{team}",payload),
                    "slate_date":slate_date,"stage":stage,"game_id":game["id"],
                    "kind":"TEAM_COVERAGE","source_url":"https://moneypuck.com/data.htm",
                    "observed_at":observed,"payload":payload})
                imported["TEAM_COVERAGE"]+=1
            roster = game.get("rosters",{}).get(team,{})
            for p in roster.get("data",{}).get("players",[]):
                row = skaters.get(str(p["id"]))
                if not row or row["team"] != team:
                    continue
                pid = str(p["id"])
                for kind, payload in (
                    ("PLAYER_PRESSURE",{"historicalShotAttempts":_num(row,"I_F_shotAttempts"),
                        "historicalShotsOnGoal":_num(row,"I_F_shotsOnGoal"),
                        "historicalExpectedGoals":_num(row,"I_F_xGoals"),
                        "highDangerShots":_num(row,"I_F_highDangerShots"),
                        "gamesPlayed":_num(row,"games_played"),
                        "evidenceType":"SEASON_AGGREGATE_NOT_RECENT_APPEARANCES"}),
                    ("PLAYER_FINISH_CREDIT",{"recipient":None,
                        "ownedGoals":_num(row,"I_F_goals"),
                        "primaryAssists":_num(row,"I_F_primaryAssists"),
                        "evidenceType":"HISTORICAL_OWN_GOALS_NOT_TONIGHT_PROJECTION","recipientUndetermined":True})):
                    ingest(con,{"evidence_id":_immutable_receipt_id(
                        f"mp-{kind}-{slate_date}-{stage}-{game['id']}-{pid}",payload),
                        "slate_date":slate_date,"stage":stage,"game_id":game["id"],
                        "player_id":pid,"kind":kind,"source_url":"https://moneypuck.com/data.htm",
                        "observed_at":observed,"payload":payload})
                    imported[kind]+=1
            imported["GOALIE_STATISTICS"] += sum(1 for (pid,t) in goalies if t==opponent)
    return {"imported":imported,"exportAsOf":export_asof,
            "source":"MoneyPuck public season aggregate CSV exports",
            "limits":"No anatomical shot impact zones, game-by-game dates, or confirmed deployment"}
