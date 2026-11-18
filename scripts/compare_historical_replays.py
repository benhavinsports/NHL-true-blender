"""Compare frozen historical replay ledgers from two engine versions on identical bundles."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def read_jsonl(path):
    return {row["date"]: row for row in
            (json.loads(line) for line in Path(path).read_text().splitlines())}


def core_ids(row):
    legs=((row.get("engineResult") or {}).get("card") or {}).get("current_legs") or []
    return [{"gameId": str(x["gameId"]), "playerId": str(x["playerId"]),
             "player": x.get("player"), "matchup": x.get("matchup")}
            for x in legs]


def grade_map(path):
    if not Path(path).exists():
        return {}
    return {x["date"]: x.get("grade") or {}
            for x in (json.loads(line) for line in Path(path).read_text().splitlines())}


def compare(baseline_path, baseline_grades_path, patched_path, patched_grades_path, output):
    baseline=read_jsonl(baseline_path)
    patched=read_jsonl(patched_path)
    bg=grade_map(baseline_grades_path)
    pg=grade_map(patched_grades_path)
    rows=[]
    for day in sorted(set(baseline)|set(patched)):
        b=baseline.get(day) or {}
        p=patched.get(day) or {}
        bcore=core_ids(b);pcore=core_ids(p)
        bids={(x["gameId"],x["playerId"]) for x in bcore}
        pids={(x["gameId"],x["playerId"]) for x in pcore}
        be=b.get("engineResult") or {};pe=p.get("engineResult") or {}
        b_g0=be.get("g0TwoGoalieDirectionDecisions") or {}
        p_g0=pe.get("g0TwoGoalieDirectionDecisions") or {}
        rows.append({
            "date":day,
            "sameSnapshotHash":b.get("snapshotSha256")==p.get("snapshotSha256"),
            "sameEvidenceDbHash":b.get("evidenceDbSha256")==p.get("evidenceDbSha256"),
            "baselineStatus":b.get("status"),"patchedStatus":p.get("status"),
            "baselineCore":bcore,"patchedCore":pcore,
            "addedToCore":[x for x in pcore if (x["gameId"],x["playerId"]) not in bids],
            "removedFromCore":[x for x in bcore if (x["gameId"],x["playerId"]) not in pids],
            "baselineSurvivors":be.get("uniqueGameSurvivors"),
            "patchedSurvivors":pe.get("uniqueGameSurvivors"),
            "baselineG0Directions":b_g0,"patchedG0Directions":p_g0,
            "G0DirectionChanged":b_g0!=p_g0,
            "baselineGrade":bg.get(day),"patchedGrade":pg.get(day),
            "selectionInputsIdentical":(
                b.get("snapshotSha256") is not None and
                b.get("snapshotSha256")==p.get("snapshotSha256") and
                b.get("evidenceDbSha256")==p.get("evidenceDbSha256")),
        })
    report={
        "baselineEngineRef":"dd3bf67 (immediately before G0 vulnerability-comparison patch 555f0b0)",
        "patchedEngineRef":"audit/historical-season-replay",
        "comparisonMethod":"same frozen snapshot and isolated evidence DB; only engine.py replaced in baseline package",
        "rows":rows,
        "sameInputRows":sum(x["selectionInputsIdentical"] for x in rows),
        "changedCoreDates":sum(x["baselineCore"]!=x["patchedCore"] for x in rows),
        "changedG0Dates":sum(x["G0DirectionChanged"] for x in rows),
        "notEvidenceOfGeneralization":True,
    }
    Path(output).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({
        "output":str(output),"dates":len(rows),
        "sameInputRows":report["sameInputRows"],
        "changedCoreDates":report["changedCoreDates"],
        "changedG0Dates":report["changedG0Dates"],
    },sort_keys=True))
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline")
    p.add_argument("baseline_grades")
    p.add_argument("patched")
    p.add_argument("patched_grades")
    p.add_argument("output")
    a=p.parse_args()
    compare(a.baseline,a.baseline_grades,a.patched,a.patched_grades,a.output)


if __name__=="__main__":
    main()
