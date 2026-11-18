"""Aggregate official replay ledgers into per-slate and gate-by-gate audit reports."""
import argparse, json
from collections import Counter
from pathlib import Path

GATES = [f"G{i}" for i in range(1,11)] + ["G10.5"] + [f"G{i}" for i in range(11,19)]

def read_jsonl(path):
    p=Path(path)
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

def gate_counts(row):
    matrix=(row.get("gateDiagnostics") or {}).get("candidateGateMatrix") or []
    matrix=[x for x in matrix if not str(x.get("playerId","")).startswith("G0_RESEARCH:")]
    out={}
    for gate in GATES:
        idx=GATES.index(gate); c=Counter()
        for player in matrix:
            first=player.get("firstNonpassingMasterGate")
            fi=GATES.index(first) if first in GATES else (len(GATES) if first in (None,"FULL_PASS") else -1)
            disp=(player.get("masterDispositions") or {}).get(gate,"NOT_EXECUTED")
            if fi>=0 and fi<idx:
                c["neverReached"]+=1
            else:
                c["reached"]+=1
                if disp=="PASS": c["passed"]+=1
                elif first==gate and disp=="ELIMINATED": c["meritFailed"]+=1
                elif first==gate and disp in ("NOT_EXECUTED","BLOCKED","UNRESOLVED"): c["evidenceBlocked"]+=1
                else: c["otherUnresolved"]+=1
        out[gate]=dict(c)
    return len(matrix),out

def grade_summary(g):
    if not g:return None
    return {"status":g.get("status"),"hits":g.get("hits"),"legs":g.get("legs"),
            "result":g.get("result"),"playerResults":[
                {k:x.get(k) for k in ("player","playerId","gameId","goals","participation","result")}
                for x in g.get("playerResults",[])]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("manifest");p.add_argument("selections");p.add_argument("grades")
    p.add_argument("postgame");p.add_argument("comparison");p.add_argument("output")
    a=p.parse_args()
    manifest=json.loads(Path(a.manifest).read_text())
    sels={x["date"]:x for x in read_jsonl(a.selections)}
    grades={x["date"]:x.get("grade") or {} for x in read_jsonl(a.grades)}
    post={x["date"]:x for x in read_jsonl(a.postgame)}
    cmp=json.loads(Path(a.comparison).read_text()) if Path(a.comparison).exists() else {}
    scheduled=sorted(manifest.get("scheduledDates",[]));off=set(manifest.get("verifiedOffDays",[]))
    per=[];agg={g:Counter() for g in GATES}
    for day in sorted(set(scheduled)|off):
        s=sels.get(day) or {"date":day,"status":"MISSING_SELECTION_LEDGER_ROW"}
        e=s.get("engineResult") or {};card=e.get("card") or {};legs=card.get("current_legs") or []
        g=grades.get(day) or {}; pg=post.get(day) or {}
        n,counts=gate_counts(s) if s.get("status")=="REPLAYED" else (0,{})
        for gate,values in counts.items():agg[gate].update(values)
        sched=(manifest.get("officialSchedule") or {}).get(day) or {}
        per.append({
            "date":day,"scheduleStatus":"VERIFIED_OFF_DAY" if day in off else "SCHEDULED",
            "games":len(sched.get("games") or []),
            "matchups":[x.get("away","")+"@"+x.get("home","") for x in sched.get("games") or []],
            "replayStatus":s.get("status"),"cutoff":s.get("cutoff"),"stage":s.get("stage"),
            "candidatePlayers":n,"gateCertified":(s.get("gateCertification") or {}).get("selectedCoreOnlyFullyCertified"),
            "g0":{"directionsRequired":e.get("games",0)*2,"directionsWithCompleteProfiles":e.get("g0Complete"),
                  "directionsScanned":e.get("g0Directions"),"attackSidesSelected":len(e.get("g0TwoGoalieDirectionDecisions") or {}),
                  "gamesWithoutAttackSide":e.get("games",0)-len(e.get("g0TwoGoalieDirectionDecisions") or {})} if s.get("status")=="REPLAYED" else None,
            "survivors":[{"matchup":x.get("matchup"),"status":x.get("status"),
                          "player":(x.get("survivor") or {}).get("player"),
                          "firstNonPassGateCounts":x.get("firstNonPassGateCounts")}
                         for x in e.get("gameSurvivorPool",[])],
            "core":[{"player":x.get("player"),"playerId":x.get("playerId"),"gameId":x.get("gameId")} for x in legs],
            "gateCounts":counts,"firstNonpassing":(s.get("firstNonpassingGateAudit") or {}).get("firstNonpassingGateCounts"),
            "grade":grade_summary(g),"G16":e.get("g16FinalistCompetition"),
            "g0PostgameTeamGoalComparisons":pg.get("g0TeamGoalComparisons"),
            "G10_5PostgameComparisons":pg.get("G10_5PregameVsOfficialScorers"),
            "postgameResearchStatus":pg.get("status"),"samePoolBaseline":pg.get("samePoolBaseline")
        })
    graded=[x for x in per if (x.get("grade") or {}).get("status")=="GRADED_FINAL_BOXSCORE_AND_PBP"]
    complete=[x for x in per if x["replayStatus"]=="REPLAYED" and x["gateCertified"] is True
              and (x.get("grade") or {}).get("status")=="GRADED_FINAL_BOXSCORE_AND_PBP"]
    hits=sum((x.get("grade") or {}).get("hits") or 0 for x in graded)
    legs=sum((x.get("grade") or {}).get("legs") or 0 for x in graded)
    dressed=sum(r.get("participation")=="LISTED_AS_DRESSED_SKATER" for x in graded for r in (x.get("grade") or {}).get("playerResults",[]))
    absent=sum(r.get("participation")=="NOT_LISTED_IN_OFFICIAL_BOXSCORE" for x in graded for r in (x.get("grade") or {}).get("playerResults",[]))
    core3=[x for x in graded if (x.get("grade") or {}).get("legs")==3]
    g105_merit=[];g105_blocked=[];g105rows=[]
    g0_selected=[]
    for day, report_row in post.items():
        if report_row.get("status")!="OFFICIAL_POSTGAME_RESEARCH_COMPLETE":continue
        selection=sels.get(day) or {}
        matrix=(selection.get("gateDiagnostics") or {}).get("candidateGateMatrix") or []
        dispositions={(str(x.get("gameId")),str(x.get("playerId"))):
                      (x.get("masterDispositions") or {}).get("G10.5")
                      for x in matrix if not str(x.get("playerId","")).startswith("G0_RESEARCH:")}
        cmap={(x.get("gameId"),x.get("playerId")):x
              for x in report_row.get("candidateFirstGateAndOfficialScoring",[])}
        for key,candidate in cmap.items():
            if candidate.get("firstNonpassingMasterGate")!="G10.5":continue
            status=dispositions.get((str(key[0]),str(key[1])))
            if status=="ELIMINATED":g105_merit.append(candidate)
            elif status=="NOT_EXECUTED":g105_blocked.append(candidate)
        for row in report_row.get("G10_5PregameVsOfficialScorers",[]):
            key=(str(row.get("gameId")),str(row.get("candidateId")))
            if dispositions.get(key)=="ELIMINATED" and cmap.get((row.get("gameId"),row.get("candidateId")),{}).get("firstNonpassingMasterGate")=="G10.5":
                g105rows.append(row)
        for row in report_row.get("g0TeamGoalComparisons",[]):
            if row.get("pregameAttackSideWasSelected"):
                g0_selected.append(row)
    challengers={}
    for row in g105rows:
        if row.get("challengerOfficialGoals",0)>0:
            key=(row.get("gameId"),row.get("challengerId"))
            prior=challengers.get(key,{"player":row.get("challenger"),"goals":0,"shotsInLane":0,"goalsInLane":0})
            prior["goals"]=max(prior["goals"],row.get("challengerOfficialGoals",0))
            prior["shotsInLane"]=max(prior["shotsInLane"],row.get("challengerOnNetShotsInPregameApproximateLane",0) or 0)
            prior["goalsInLane"]=max(prior["goalsInLane"],row.get("challengerGoalsInPregameApproximateLane",0) or 0)
            challengers[key]=prior
    candidate_lane={}
    for row in g105rows:
        if row.get("candidateOfficialGoals",0)>0:
            key=(row.get("gameId"),row.get("candidateId"))
            prior=candidate_lane.get(key,{"player":row.get("candidate"),"goals":0,"shotsInLane":0,"goalsInLane":0})
            prior["goals"]=max(prior["goals"],row.get("candidateOfficialGoals",0))
            prior["shotsInLane"]=max(prior["shotsInLane"],row.get("candidateOnNetShotsInPregameApproximateLane",0) or 0)
            prior["goalsInLane"]=max(prior["goalsInLane"],row.get("candidateGoalsInPregameApproximateLane",0) or 0)
            candidate_lane[key]=prior
    report={
        "dateRange":{"start":manifest["start"],"end":manifest["end"]},
        "officialSchedule":{"scheduledSlates":len(scheduled),"verifiedOffDays":len(off),
            "scheduledGames":sum(len((manifest.get("officialSchedule") or {}).get(d,{}).get("games") or []) for d in scheduled),
            "scheduledDates":scheduled,"offDays":sorted(off)},
        "completion":{"fullyCompletedSlates":len(complete),"unresolvedScheduledSlates":len(scheduled)-len(complete),
            "replayStatusCounts":dict(Counter(x["replayStatus"] for x in per if x["scheduleStatus"]=="SCHEDULED")),
            "openingWeek":{"start":"2026-09-29","end":"2026-10-05",
                "scheduledSlates":sum("2026-09-29"<=d<="2026-10-05" for d in scheduled),
                "fullyCompletedSlates":sum("2026-09-29"<=x["date"]<="2026-10-05" for x in complete)}},
        "grading":{"gradedCards":len(graded),"legHits":hits,"legOpportunities":legs,
            "dressedPicks":dressed,"notListedInOfficialBoxscore":absent,
            "fullCardsHit":sum((x.get("grade") or {}).get("result")=="WIN" for x in graded),
            "fullCardsGraded":len(graded),
            "Core3":{"cards":len(core3),"hits":sum((x.get("grade") or {}).get("hits") or 0 for x in core3),
                     "legs":sum((x.get("grade") or {}).get("legs") or 0 for x in core3),
                     "fullCardsHit":sum((x.get("grade") or {}).get("result")=="WIN" for x in core3)},
            "otherCardSizes":dict(Counter((x.get("grade") or {}).get("legs") for x in graded if (x.get("grade") or {}).get("legs")!=3))},
        "gateBreakdown":{"order":GATES,"aggregate":{g:dict(agg[g]) for g in GATES},
                         "playerCandidateDenominator":sum(gate_counts(x)[0] for x in sels.values() if x.get("status")=="REPLAYED"),
                         "G0ReportedAsGameDirectionsSeparately":True},
        "G0PostgameTeamGoalComparison":{
            "selectedAttackSides":len(g0_selected),
            "selectedSideScoredMore":sum((x.get("pregameAttackSideGoals") or 0)>(x.get("oppositeSideGoals") or 0) for x in g0_selected),
            "oppositeSideScoredMore":sum((x.get("pregameAttackSideGoals") or 0)<(x.get("oppositeSideGoals") or 0) for x in g0_selected),
            "ties":sum((x.get("pregameAttackSideGoals") or 0)==(x.get("oppositeSideGoals") or 0) for x in g0_selected),
            "teamGoalsAreNotIndividualRouteProof":True},
        "G10_5":{
            "firstMeritFailureCandidates":len(g105_merit),
            "meritFailureCandidatesWhoScored":sum(x.get("officialGoals",0)>0 for x in g105_merit),
            "evidenceBlockedAtG10_5":len(g105_blocked),
            "evidenceBlockedCandidatesWhoScored":sum(x.get("officialGoals",0)>0 for x in g105_blocked),
            "sameLaneComparisonRowsForMeritFailures":len(g105rows),
            "meritFailureChallengersWhoScored":len(challengers),
            "scoredChallengersWithOnNetShotInSameApproximateLane":sum(x["shotsInLane"]>0 for x in challengers.values()),
            "scoredChallengersWithGoalInSameApproximateLane":sum(x["goalsInLane"]>0 for x in challengers.values()),
            "scoredMeritFailureCandidates":[{"player":x.get("player"),"gameId":x.get("gameId"),"goals":x.get("officialGoals")} for x in g105_merit if x.get("officialGoals",0)>0],
            "scoredChallengers":[{"player":v["player"],"goals":v["goals"],"onNetShotsInLane":v["shotsInLane"],"goalsInLane":v["goalsInLane"]} for v in challengers.values()],
            "scoredMeritFailureCandidatesLaneOpportunities":[{"player":v["player"],"goals":v["goals"],"onNetShotsInLane":v["shotsInLane"],"goalsInLane":v["goalsInLane"]} for v in candidate_lane.values()],
            "fullComparisonRowsAreInPostgameResearchJsonl":True,
            "postgameIsDiagnosticNotPregameProof":True},
        "baselineVersusPatch":{"baselineEngineRef":cmp.get("baselineEngineRef"),
            "sameInputRows":cmp.get("sameInputRows"),"changedG0Dates":cmp.get("changedG0Dates"),
            "changedCoreDates":cmp.get("changedCoreDates"),"rows":cmp.get("rows")},
        "perSlate":per,
        "pointInTimeQualification":"Collector observation times and explicit historical event dates are audited. Provider internal as-of times remain unverified for source families that do not expose them."
    }
    out=Path(a.output);out.write_text(json.dumps(report,indent=2,default=str))
    md=["# Historical NHL True Blender Audit",f"Period: {manifest['start']} through {manifest['end']}","",
        f"- Scheduled slates: {len(scheduled)}; verified off days: {len(off)}",
        f"- Fully completed slates: {len(complete)}; unresolved scheduled slates: {len(scheduled)-len(complete)}",
        f"- Graded cards: {len(graded)}; leg hits: {hits}/{legs}; dressed picks: {dressed}; not listed in boxscore: {absent}",
        f"- Full cards hit: {sum((x.get('grade') or {}).get('result')=='WIN' for x in graded)}/{len(graded)}",
        "", "## Gate breakdown (first nonpassing gate only)",
        "| Gate | Reached | Passed | Merit failures | Evidence blocked | Never reached |","|---|---:|---:|---:|---:|---:|"]
    for g in GATES:
        x=agg[g];md.append(f"| {g} | {x['reached']} | {x['passed']} | {x['meritFailed']} | {x['evidenceBlocked']} | {x['neverReached']} |")
    md += ["","## Per-slate","| Date | Games | Replay | Survivors | Core | Certified | Grade |","|---|---:|---|---:|---|---|---|"]
    for x in per:
        core=", ".join(y["player"] or y["playerId"] for y in x["core"]) or "—"
        g=x.get("grade") or {};gt=f"{g.get('hits')}/{g.get('legs')} {g.get('result')}" if g.get("legs") else g.get("status","—")
        md.append(f"| {x['date']} | {x['games']} | {x['replayStatus']} | {sum(y['status']=='SURVIVOR' for y in x['survivors'])} | {core} | {x['gateCertified']} | {gt} |")
    md += ["","## G0 postgame side comparison",
           f"- Selected attack sides: {len(g0_selected)}; selected side outscored the opposite side: {sum((x.get('pregameAttackSideGoals') or 0)>(x.get('oppositeSideGoals') or 0) for x in g0_selected)}/{len(g0_selected)}.",
           "- Team goals are not evidence of an individual skater's route.",
           "", "## G10.5 postgame diagnostic",
           f"- Merit failures: {len(g105_merit)}; merit-failed candidates who scored: {sum(x.get('officialGoals',0)>0 for x in g105_merit)}.",
           f"- Evidence-blocked at G10.5: {len(g105_blocked)}.",
           f"- Same-lane comparison rows for merit failures: {len(g105rows)}; scored challengers: {len(challengers)}.",
           "- Full candidate/challenger rows, including approximate-lane opportunities, are in postgame-research.jsonl.",
           "",report["pointInTimeQualification"]]
    out.with_suffix(".md").write_text("\n".join(md)+"\n")
    print(json.dumps({"json":str(out),"markdown":str(out.with_suffix(".md")),
        "scheduledSlates":len(scheduled),"fullyCompleted":len(complete),"legHits":hits,"legOpportunities":legs}))
if __name__=="__main__":main()
