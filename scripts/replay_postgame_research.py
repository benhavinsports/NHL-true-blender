"""Postgame-only scorer, G10.5, G0-direction and shot-origin audit for replay ledgers.

This script runs only after the frozen selection ledger exists. Its outputs are
diagnostic and never feed the historical selector or change a frozen pick.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter, defaultdict
from pathlib import Path

from nhl_true_blender_engine.historical_shots import extract_events, ON_NET
from nhl_true_blender_engine.official_defense_coverage import (
    conservative_zone, detailed_shot_origin_zone,
)
from nhl_true_blender_engine.sources import (
    NHLClient, SourceUnavailable, credited_goals_from_pbp,
)


def _approx_zones(event):
    return sorted(set(filter(None, (
        conservative_zone(event.get("x"), event.get("y")),
        detailed_shot_origin_zone(event.get("x"), event.get("y")),
    ))))


def _display_name(value, fallback=None):
    if isinstance(value, dict):
        value = value.get("default") or value.get("fullName") or value.get("name")
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(fallback, dict):
        fallback = fallback.get("default") or fallback.get("fullName")
    return fallback if isinstance(fallback, str) else None


def _roster_names(snapshot):
    names = {}
    teams = {}
    for game in snapshot.get("games", []):
        for team, receipt in (game.get("rosters") or {}).items():
            data = (receipt or {}).get("data") or {}
            for player in data.get("players") or []:
                pid = str(player.get("id") or "")
                if pid:
                    names[pid] = _display_name(player.get("name"), player.get("fullName"))
                    teams[(str(game["id"]), pid)] = team
    return names, teams


def _baseline(survivors, card_size):
    """Simple pregame same-pool baseline: highest own SOG, one per game."""
    ordered = sorted(
        survivors,
        key=lambda x: (-int(x.get("ownShotsOnGoal") or 0),
                       str(x.get("gameId")), str(x.get("playerId"))),
    )
    chosen = []
    used_games = set()
    for item in ordered:
        gid = str(item.get("gameId"))
        if gid in used_games:
            continue
        chosen.append(item)
        used_games.add(gid)
        if len(chosen) == card_size:
            break
    return chosen


async def audit_day(selection, manifest, root):
    day = selection["date"]
    bundle = (manifest.get("slates") or {}).get(day)
    if not bundle:
        return {"date": day, "status": "NO_PREGAME_BUNDLE", "postgameAudit": False}
    snapshot = json.loads((root / bundle["snapshot"]).read_text(encoding="utf-8"))
    names, roster_teams = _roster_names(snapshot)
    engine = selection.get("engineResult") or {}
    matrix = (selection.get("gateDiagnostics") or {}).get("candidateGateMatrix") or []
    survivors = [
        item["survivor"] for item in (engine.get("gameSurvivorPool") or [])
        if item.get("status") == "SURVIVOR" and item.get("survivor")
    ]
    core = ((engine.get("card") or {}).get("current_legs") or [])
    selected = {(str(x["gameId"]), str(x["playerId"])) for x in core}
    game_rows = {str(g["id"]): g for g in snapshot.get("games", [])}
    client = NHLClient()
    audited = {}
    try:
        for game_id, game in sorted(game_rows.items()):
            box_report = await client.boxscore(game_id)
            box = box_report["data"]
            if str(box.get("id")) != game_id or box.get("gameState") not in ("FINAL", "OFF"):
                raise SourceUnavailable(f"Official final boxscore/game identity unavailable: {game_id}")
            pbp_report = await client.play_by_play(game_id)
            pbp = pbp_report["data"]
            if pbp.get("id") is not None and str(pbp["id"]) != game_id:
                raise SourceUnavailable(f"Official PBP game ID mismatch: {game_id}")
            counts, goal_event_ids = credited_goals_from_pbp(pbp_report)
            stats = box.get("playerByGameStats") or {}
            players = {}
            for side in ("homeTeam", "awayTeam"):
                team_code = game["home"] if side == "homeTeam" else game["away"]
                for position in ("forwards", "defense"):
                    for player in (stats.get(side) or {}).get(position, []):
                        pid = str(player.get("playerId") or "")
                        if not pid or pid in players:
                            raise SourceUnavailable(f"Missing/duplicate official player ID in {game_id}")
                        goals = player.get("goals")
                        if type(goals) is not int or goals < 0:
                            raise SourceUnavailable(f"Invalid official goals for {game_id}/{pid}")
                        if goals != counts.get(pid, 0):
                            raise SourceUnavailable(f"PBP/boxscore goal mismatch for {game_id}/{pid}")
                        players[pid] = {
                            "playerId": pid,
                            "player": _display_name(player.get("name"), names.get(pid)),
                            "team": team_code,
                            "goals": goals,
                            "listedInOfficialBoxscore": True,
                        }
            if not players:
                raise SourceUnavailable(f"Official boxscore has no skaters: {game_id}")
            if set(counts) - set(players):
                raise SourceUnavailable(f"PBP credited scorer absent from boxscore: {game_id}")

            events = extract_events(pbp_report, game_id, day)
            by_shooter = defaultdict(list)
            goalies_observed = set()
            for event in events:
                event["approximateZones"] = _approx_zones(event)
                by_shooter[str(event["shooterId"])].append(event)
                if event.get("goalieId"):
                    goalies_observed.add(str(event["goalieId"]))
            for pid, record in players.items():
                record["shots"] = len(by_shooter.get(pid, []))
                record["onNetShots"] = sum(
                    x["type"] in ON_NET for x in by_shooter.get(pid, []))
                record["onNetByApproximateZone"] = dict(Counter(
                    zone for x in by_shooter.get(pid, []) if x["type"] in ON_NET
                    for zone in x["approximateZones"]))
                record["shotEventLocations"] = [
                    {"eventId": x["eventId"], "type": x["type"],
                     "x": x.get("x"), "y": x.get("y"),
                     "approximateZones": x["approximateZones"],
                     "goalieId": x.get("goalieId"),
                     "period": x.get("period"), "timeInPeriod": x.get("timeInPeriod")}
                    for x in by_shooter.get(pid, [])
                ]
                record["goalEvents"] = [
                    x for x in record["shotEventLocations"] if x["type"] == "goal"
                ]
            scorers = sorted(
                [x for x in players.values() if x["goals"] > 0],
                key=lambda x: (x["team"], str(x["player"] or ""), x["playerId"]),
            )
            audited[game_id] = {
                "matchup": game["away"] + "@" + game["home"],
                "away": game["away"], "home": game["home"],
                "teamGoals": {
                    game["away"]: sum(x["goals"] for x in players.values() if x["team"] == game["away"]),
                    game["home"]: sum(x["goals"] for x in players.values() if x["team"] == game["home"]),
                },
                "officialScorers": scorers,
                "players": players,
                "goaliesObservedInPbp": sorted(goalies_observed),
                "officialSources": [box_report["url"], pbp_report["url"]],
                "allSkaterGoalTotalsReconciled": True,
                "shotCoordinatesAreRinkOriginNotGoalMouthImpact": True,
            }
    finally:
        await client.close()

    # Candidate outcomes are joined only after selection was frozen.
    candidate_rows = []
    for row in matrix:
        pid = str(row.get("playerId") or "")
        gid = str(row.get("gameId") or "")
        if pid.startswith("G0_RESEARCH:") or gid not in audited:
            continue
        game_audit = audited[gid]
        actual = game_audit["players"].get(pid)
        candidate_rows.append({
            "gameId": gid, "matchup": game_audit["matchup"],
            "playerId": pid, "player": names.get(pid),
            "team": roster_teams.get((gid, pid)),
            "firstNonpassingMasterGate": row.get("firstNonpassingMasterGate"),
            "officialParticipation": "LISTED_IN_BOXSCORE" if actual else "NOT_LISTED_IN_BOXSCORE",
            "officialGoals": actual["goals"] if actual else 0,
            "officialOnNetShots": actual["onNetShots"] if actual else 0,
            "officialApproximateOnNetZones": actual["onNetByApproximateZone"] if actual else {},
            "officialShotEventLocations": actual["shotEventLocations"] if actual else [],
            "G10_5PregameComparison": (row.get("nonpassReasons") or {}).get("G10.5"),
        })

    # Add every same-lane challenger referenced by a failed G10.5 comparison.
    # Survivor path receipts also preserve the direct-primary IDs they displaced.
    g105_reviews = []
    seen_pairs = set()
    for row in matrix:
        pid = str(row.get("playerId") or "")
        gid = str(row.get("gameId") or "")
        if pid.startswith("G0_RESEARCH:") or gid not in audited:
            continue
        reasons = row.get("nonpassReasons") or {}
        g105 = reasons.get("G10.5") or {}
        comparisons = g105.get("firstDirectContradictions") or []
        first_gate = row.get("firstNonpassingMasterGate")
        gate_order = [f"G{i}" for i in range(1, 11)] + ["G10.5"] + [f"G{i}" for i in range(11, 19)]
        first_index = gate_order.index(first_gate) if first_gate in gate_order else len(gate_order)
        if first_index < gate_order.index("G10.5"):
            continue
        if (row.get("masterDispositions") or {}).get("G10.5") not in ("PASS", "ELIMINATED"):
            continue
        for comparison in comparisons:
            challenger_id = str(comparison.get("challengerId") or "")
            key = (gid, pid, challenger_id)
            if not challenger_id or key in seen_pairs:
                continue
            seen_pairs.add(key)
            candidate_actual = audited[gid]["players"].get(pid)
            challenger_actual = audited[gid]["players"].get(challenger_id)
            candidate_comparison = comparison.get("candidate") or {}
            challenger_comparison = comparison.get("challenger") or {}
            g105_reviews.append({
                "gameId": gid, "matchup": audited[gid]["matchup"],
                "candidateId": pid, "candidate": names.get(pid),
                "challengerId": challenger_id, "challenger": names.get(challenger_id),
                "pregameVerdict": comparison.get("status"),
                "pregameSameLane": candidate_comparison.get("zone"),
                "pregameCandidate": candidate_comparison,
                "pregameChallenger": challenger_comparison,
                "candidateOfficialGoals": candidate_actual["goals"] if candidate_actual else 0,
                "candidateOfficialOnNetShots": candidate_actual["onNetShots"] if candidate_actual else 0,
                "challengerOfficialGoals": challenger_actual["goals"] if challenger_actual else 0,
                "challengerOfficialOnNetShots": challenger_actual["onNetShots"] if challenger_actual else 0,
                "challengerParticipation": "LISTED_IN_BOXSCORE" if challenger_actual else "NOT_LISTED_IN_BOXSCORE",
                "postgameDoesNotProvePregameDecisionWrong": True,
            })

    for survivor in survivors:
        gid, pid = str(survivor["gameId"]), str(survivor["playerId"])
        for displaced in ((survivor.get("pathClassificationEvidence") or {}).get(
                "G10_5DisplacedPrimaryEvidence") or []):
            challenger_id = str(displaced.get("displacedDirectPrimaryPlayerId") or "")
            key = (gid, pid, challenger_id)
            if not challenger_id or key in seen_pairs:
                continue
            seen_pairs.add(key)
            candidate_actual = audited[gid]["players"].get(pid)
            challenger_actual = audited[gid]["players"].get(challenger_id)
            g105_reviews.append({
                "gameId": gid, "matchup": audited[gid]["matchup"],
                "candidateId": pid, "candidate": survivor.get("player"),
                "challengerId": challenger_id, "challenger": names.get(challenger_id),
                "pregameVerdict": displaced.get("G10_5Verdict"),
                "pregameSameLane": displaced.get("sameLane"),
                "pregameCandidate": {
                    "ownedGoals": displaced.get("directGoalCreditCandidate"),
                    "shotsOnGoal": survivor.get("ownShotsOnGoal"),
                },
                "pregameChallenger": {
                    "ownedGoals": displaced.get("directGoalCreditPrior"),
                    "shotsOnGoal": None,
                    "shotsOnGoalNotIncludedInSurvivorPathReceipt": True,
                },
                "candidateOfficialGoals": candidate_actual["goals"] if candidate_actual else 0,
                "candidateOfficialOnNetShots": candidate_actual["onNetShots"] if candidate_actual else 0,
                "challengerOfficialGoals": challenger_actual["goals"] if challenger_actual else 0,
                "challengerOfficialOnNetShots": challenger_actual["onNetShots"] if challenger_actual else 0,
                "challengerParticipation": "LISTED_IN_BOXSCORE" if challenger_actual else "NOT_LISTED_IN_BOXSCORE",
                "postgameDoesNotProvePregameDecisionWrong": True,
            })

    g0 = engine.get("g0TwoGoalieDirectionDecisions") or {}
    g0_comparison = []
    for gid, game in game_rows.items():
        decision = g0.get(gid) or {}
        attack = decision.get("attackingTeam") or decision.get("attackTeam")
        opponent = decision.get("targetGoalieTeam") or decision.get("opponentTeam")
        team_goals = audited[gid]["teamGoals"]
        g0_comparison.append({
            "gameId": gid, "matchup": audited[gid]["matchup"],
            "pregameAttackTeam": attack, "pregameTargetGoalieTeam": opponent,
            "pregameAttackSideWasSelected": bool(attack),
            "pregameAttackSideGoals": team_goals.get(attack) if attack else None,
            "oppositeSideGoals": team_goals.get(opponent) if opponent else None,
            "actualTeamGoals": team_goals,
            "bothSidesWereSourceReviewedBeforeSelection": bool(decision.get("bothGoaliesReviewedFirst")),
            "teamGoalsAreNotProofOfIndividualScorerRoute": True,
        })

    survivor_rows = []
    baseline = _baseline(survivors, len(core)) if core else []
    baseline_results = []
    for survivor in survivors:
        gid, pid = str(survivor["gameId"]), str(survivor["playerId"])
        actual = audited[gid]["players"].get(pid)
        route = survivor.get("ownRouteZone")
        # Events are represented in the player's reconciled boxscore detail.
        zones = (actual or {}).get("onNetByApproximateZone", {})
        lane_shots = int(zones.get(route, 0)) if route else 0
        all_on_net = (actual or {}).get("onNetShots", 0)
        goals = (actual or {}).get("goals", 0)
        if not route:
            route_result = "ROUTE_UNMAPPED"
        elif lane_shots and goals:
            route_result = "GOAL_CREDITED_AND_ON_NET_OPPORTUNITY_IN_PREDICTED_APPROXIMATE_LANE"
        elif lane_shots:
            route_result = "PREDICTED_LANE_OPPORTUNITY_DID_NOT_CONVERT"
        elif all_on_net:
            route_result = "ON_NET_SHOTS_OBSERVED_OUTSIDE_PREDICTED_APPROXIMATE_LANE"
        else:
            route_result = "NO_ON_NET_SHOTS_OBSERVED"
        survivor_rows.append({
            "gameId": gid, "matchup": survivor.get("matchup"),
            "playerId": pid, "player": survivor.get("player"),
            "attackTeam": survivor.get("attackTeam"),
            "predictedGoalieId": survivor.get("goalieId"),
            "actualGoalieIdsObserved": audited[gid]["goaliesObservedInPbp"],
            "predictedGoalieObservedInPbp": str(survivor.get("goalieId")) in audited[gid]["goaliesObservedInPbp"],
            "predictedShotRoute": route,
            "pregameOwnedGoalsInRoute": survivor.get("ownedGoals"),
            "pregameOwnShotsOnGoalInRoute": survivor.get("ownShotsOnGoal"),
            "officialGoals": goals,
            "officialOnNetShots": all_on_net,
            "officialOnNetShotsInPredictedApproximateLane": lane_shots,
            "routeOutcome": route_result,
            "selectedInCore": (gid, pid) in selected,
            "notListedInBoxscore": actual is None,
        })
    for survivor in baseline:
        gid, pid = str(survivor["gameId"]), str(survivor["playerId"])
        actual = audited[gid]["players"].get(pid)
        baseline_results.append({
            "gameId": gid, "playerId": pid, "player": survivor.get("player"),
            "goals": (actual or {}).get("goals", 0),
            "result": "HIT" if (actual or {}).get("goals", 0) else "MISS",
        })
    baseline_hits = sum(x["result"] == "HIT" for x in baseline_results)
    return {
        "date": day, "status": "OFFICIAL_POSTGAME_RESEARCH_COMPLETE",
        "cardId": (engine.get("card") or {}).get("card_id"),
        "coreSize": len(core), "g0TeamGoalComparisons": g0_comparison,
        "allGameOfficialResults": audited,
        "candidateFirstGateAndOfficialScoring": candidate_rows,
        "G10_5PregameVsOfficialScorers": g105_reviews,
        "gameSurvivorsAndRouteOutcomes": survivor_rows,
        "samePoolBaseline": {
            "method": "HIGHEST_PREGAME_OWN_SHOTS_ON_GOAL_ONE_PER_GAME",
            "picks": baseline_results,
            "hits": baseline_hits,
            "legs": len(baseline_results),
            "result": ("WIN" if baseline_results and baseline_hits == len(baseline_results)
                       else "LOSS" if baseline_results else "NO_BASELINE_CARD"),
            "sameSurvivorPool": True,
            "sameSlateCoverage": True,
            "sameCardSizeWhenEnoughSurvivors": len(baseline_results) == len(core),
        },
        "officialScoringSourcesReconciled": True,
        "rinkCoordinateZonesAreApproximateNotNhlEdgePolygons": True,
        "goalMouthAnatomyNotInferredFromRinkCoordinates": True,
        "postgameDataNeverFeedsSelector": True,
        "readOnly": True,
    }


async def main_async(manifest_path: Path, selections_path: Path, output_path: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    rows = []
    for line in selections_path.read_text(encoding="utf-8").splitlines():
        selection = json.loads(line)
        if selection.get("status") != "REPLAYED":
            rows.append({"date": selection.get("date"),
                         "status": selection.get("status"),
                         "postgameAudit": False})
            continue
        try:
            rows.append(await audit_day(selection, manifest, root))
        except Exception as exc:
            rows.append({"date": selection.get("date"),
                         "status": "POSTGAME_RESEARCH_UNAVAILABLE",
                         "errorType": type(exc).__name__, "error": str(exc),
                         "postgameDataNeverFeedsSelector": True})
    with output_path.open("x", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, default=str, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output_path),
        "dates": len(rows),
        "completed": sum(x.get("status") == "OFFICIAL_POSTGAME_RESEARCH_COMPLETE" for x in rows),
        "unavailable": sum(x.get("status") == "POSTGAME_RESEARCH_UNAVAILABLE" for x in rows),
    }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("selections", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(main_async(args.manifest, args.selections, args.output))


if __name__ == "__main__":
    main()
