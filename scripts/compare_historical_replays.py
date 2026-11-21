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
        # A causal baseline-vs-patched comparison is only meaningful when
        # BOTH versions used the exact same pre-puck clock, stage, snapshot
        # AND isolated evidence DB. Nov 17 in the saved 50-slate report used
        # a different cutoff and both inputs differed; counting its Core
        # removal as a scorer repair was not a valid backtest result.
        same_snapshot = bool(
            b.get("snapshotSha256") and
            b["snapshotSha256"] == p.get("snapshotSha256"))
        same_evidence = bool(
            b.get("evidenceDbSha256") and
            b["evidenceDbSha256"] == p.get("evidenceDbSha256"))
        same_cutoff = bool(
            b.get("cutoff") and b["cutoff"] == p.get("cutoff") and
            b.get("stage") and b["stage"] == p.get("stage"))
        comparable = bool(b and p and same_snapshot and
                          same_evidence and same_cutoff)
        rows.append({
            "date":day,
            "sameSnapshotHash":same_snapshot,
            "sameEvidenceDbHash":same_evidence,
            "sameCutoffAndStage":same_cutoff,
            "baselineCutoff":b.get("cutoff"),"patchedCutoff":p.get("cutoff"),
            "baselineStatus":b.get("status"),"patchedStatus":p.get("status"),
            "baselineCore":bcore,"patchedCore":pcore,
            "addedToCore":[x for x in pcore if (x["gameId"],x["playerId"]) not in bids] if comparable else [],
            "removedFromCore":[x for x in bcore if (x["gameId"],x["playerId"]) not in pids] if comparable else [],
            "uncomparableRawCoreDifference":bcore != pcore if not comparable else False,
            "baselineSurvivors":be.get("uniqueGameSurvivors"),
            "patchedSurvivors":pe.get("uniqueGameSurvivors"),
            "baselineG0Directions":b_g0,"patchedG0Directions":p_g0,
            "G0DirectionChanged":comparable and b_g0!=p_g0,
            "uncomparableRawG0Difference":b_g0!=p_g0 if not comparable else False,
            "baselineGrade":bg.get(day),"patchedGrade":pg.get(day),
            "selectionInputsIdentical":comparable,
            "excludedFromCausalComparison":not comparable,
            "comparisonExclusionReason":(
                [name for name, condition in (
                    ("SNAPSHOT_HASH_DIFFERS", same_snapshot),
                    ("EVIDENCE_DB_HASH_DIFFERS", same_evidence),
                    ("CUTOFF_OR_STAGE_DIFFERS", same_cutoff))
                 if not condition] if not comparable else []),
        })
    report={
        "baselineEngineRef":"dd3bf67 (immediately before G0 vulnerability-comparison patch 555f0b0)",
        "patchedEngineRef":"audit/historical-season-replay",
        "comparisonMethod":"Only rows with identical pre-puck cutoff, stage, snapshot SHA and isolated evidence DB SHA can attribute a selection difference to engine logic",
        "rows":rows,
        "sameInputRows":sum(x["selectionInputsIdentical"] for x in rows),
        "changedCoreDates":sum(x["selectionInputsIdentical"] and x["baselineCore"]!=x["patchedCore"] for x in rows),
        "changedG0Dates":sum(x["G0DirectionChanged"] for x in rows),
        "excludedComparisonDates":[x["date"] for x in rows if not x["selectionInputsIdentical"]],
        "excludedComparisonsNeverCountAsEngineRegression":True,
        "notEvidenceOfGeneralization":True,
    }
    Path(output).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({
        "output":str(output),"dates":len(rows),
        "sameInputRows":report["sameInputRows"],
        "changedCoreDates":report["changedCoreDates"],
        "changedG0Dates":report["changedG0Dates"],
        "excludedComparisonDates":report["excludedComparisonDates"],
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
