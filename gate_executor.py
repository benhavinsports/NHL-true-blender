"""Sequential, evidence-bound elimination over every evaluated skater.
Never upgrades an evidence label into a PASS or substitutes an arbitrary ranking.
"""
from __future__ import annotations

ORDER = [f"G{i}" for i in range(11)] + ["G10.5"] + [f"G{i}" for i in range(11, 19)]
NONBLOCKING = {"G8", "G13"}
FAIL = ("ELIMINATED", "FAIL", "REJECTED")
PASS = ("PASS", "LOCKED")
INCOMPLETE = ("UNRESOLVED", "PENDING", "NOT VALIDATED", "REVIEW", "PARTIAL", "NOT_EXECUTED")

def classify(status, gate_id):
    value = str(status or "").upper()
    if any(x in value for x in FAIL):
        return "ELIMINATED"
    if gate_id in NONBLOCKING and (
        "NOT USED" in value or "QUALITATIVE REVIEW" in value or "NEUTRAL" in value
    ):
        return "PASS_NONBLOCKING"
    if any(x in value for x in INCOMPLETE):
        return "EVIDENCE_MISSING"
    if any(x in value for x in PASS):
        return "PASS"
    return "EVIDENCE_MISSING"

def eliminate_player(player):
    traces = {str(x.get("gate")): x for x in player.get("gateTrace", [])}
    decisions = []
    alive = True
    complete = True
    first_failure = None
    for gate_id in ORDER:
        entry = traces.get(gate_id)
        result = classify(entry.get("status") if entry else None, gate_id)
        if not alive:
            result = "SKIPPED_AFTER_ELIMINATION"
        elif result == "ELIMINATED":
            alive = False
            first_failure = gate_id
        elif result == "EVIDENCE_MISSING":
            complete = False
        decisions.append({
            "gate": gate_id,
            "decision": result,
            "evidence": entry.get("evidence", []) if entry else [],
            "sourceStatus": entry.get("status") if entry else "MISSING",
        })
    return {
        "gameId": player.get("gameId"),
        "playerId": player.get("playerId"),
        "player": player.get("player"),
        "team": player.get("team"),
        "decisions": decisions,
        "survived": alive and complete,
        "eliminated": not alive,
        "complete": complete,
        "firstFailureGate": first_failure,
    }

def execute_gate_matrix(report):
    """Runs sequentially for every retained skater in every analyzed game."""
    results = []
    for game in report.get("games", []):
        gid = (game.get("game") or {}).get("gameId")
        for player in game.get("players", []):
            result = eliminate_player({**player, "gameId": gid})
            results.append(result)
    return {
        "gateOrder": ORDER,
        "playersEvaluated": len(results),
        "playersEliminated": sum(x["eliminated"] for x in results),
        "playersFullySurvived": sum(x["survived"] for x in results),
        "playersWithMissingEvidence": sum(x["survived"] is False and not x["eliminated"] for x in results),
        "playersEliminatedWithEvidence": sum(x["eliminated"] for x in results),
        "playerResults": results,
    }
