"""Evidence-preserving postgame miss audit. Does not silently rewrite selection rules."""
from __future__ import annotations
import json
from pathlib import Path

GATE_IDS = [f"G{i}" for i in range(11)] + ["G10.5"] + [f"G{i}" for i in range(11, 19)]

def audit_grade(date, state_dir="state"):
    folder = Path(state_dir)
    grade_file = folder / f"grade_{date}.json"
    card_file = folder / f"authoritative_core_{date}.json"
    if not grade_file.exists() or not card_file.exists():
        return {"status": "WAITING_FOR_GRADE_OR_CARD", "slateDate": date}
    grade = json.loads(grade_file.read_text(encoding="utf-8"))
    card = json.loads(card_file.read_text(encoding="utf-8"))
    if grade.get("status") != "GRADED":
        return {"status": "WAITING_FOR_FINAL_GRADE", "slateDate": date}
    picks = {(str(p["gameId"]), str(p["playerId"])): p for p in card.get("core", [])}
    missed = []
    for outcome in grade.get("players", []):
        if outcome.get("hit"):
            continue
        key = (str(outcome["gameId"]), str(outcome["playerId"]))
        pick = picks.get(key)
        if pick is None:
            return {"status": "CARD_GRADE_MISMATCH", "slateDate": date}
        traces = {str(t.get("gate")): t for t in pick.get("gateTrace", [])}
        missed.append({
            "gameId": key[0], "playerId": key[1],
            "officialGoals": outcome.get("goals"),
            "gateAudit": [{"gate": gate, "recorded": traces.get(gate),
                           "needsReview": True} for gate in GATE_IDS],
            "patchStatus": "PENDING_EVIDENCE_REVIEW",
            "note": "Miss is not proof that any particular gate failed; no automatic rule changes without causal evidence."
        })
    result = {"status": "AUDITED", "slateDate": date, "result": grade.get("result"),
              "misses": missed, "patchesApplied": []}
    target = folder / f"audit_{date}.json"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != result:
            return {"status": "AUDIT_CONFLICT", "slateDate": date}
    else:
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result

if __name__ == "__main__":
    import argparse
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    args = parser.parse_args()
    day = args.date or (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()
    print(json.dumps(audit_grade(day), indent=2))
