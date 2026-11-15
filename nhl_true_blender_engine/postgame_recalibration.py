"""Automatic postgame contradiction adjudication and original-card season history.

An official MISS alone never changes a scoring gate. Only a SOURCE-LINKED,
PRE-PUCK contradiction between a stored PASS and its own recorded evidence may
activate a predeclared, executable safety patch on FUTURE slates.
No retroactive card replacement, hand-entered pick, invented causal claim,
numerology weight, or automatic editing of live Python code.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timezone
import json

from .engine import MASTER, OVERLAY
from .storage import encode, get_card, stamp, transaction

GUARD_POLICIES = {
    "G10.5": "PATCH_G105_PREGAME_DIRECT_RECIPIENT_CONTRADICTION_V1",
    "G17": "PATCH_G17_PREGAME_SOURCE_CONTRADICTION_V1",
    "Step8": "PATCH_STEP8_PREGAME_UNSOURCED_SHIFT_V1",
}
GUARD_STATUSES = {
    "DEFEATED", "DIFFERENT_TARGET_LANE",
    "SOURCE_VERIFIED_ZERO_SHOTS_NO_DIRECT_LANE",
}
ORDER = MASTER + OVERLAY
OFFICIAL = "https://api-web.nhle.com/v1/"

def setup(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS postgame_patch_decisions (
        slate_date TEXT NOT NULL,card_id TEXT NOT NULL,
        game_id TEXT NOT NULL,player_id TEXT NOT NULL,
        policy_id TEXT NOT NULL, status TEXT NOT NULL,
        decision TEXT NOT NULL, observed_at TEXT NOT NULL,
        PRIMARY KEY (slate_date,card_id,game_id,player_id,policy_id)
    );
    CREATE TABLE IF NOT EXISTS season_calibration_history (
        season TEXT NOT NULL, as_of_date TEXT NOT NULL,
        report TEXT NOT NULL, generated_at TEXT NOT NULL,
        PRIMARY KEY (season,as_of_date)
    );
    """)

def _gate_data(row):
    if row is None:
        return {},[]
    detail=json.loads(row["details"])
    return detail.get("evidence") or {},detail.get("sourceIds") or []

def contradiction(gate, evidence):
    """Return a typed contradiction only when the recorded PASS proves its opposite.

    Purely missing/neutral observations are not themselves grounds for a
    postgame rule change; the original gate's actual pregame status is retained.
    """
    if gate=="G10.5":
        comparisons=evidence.get("comparisonRows")
        if not isinstance(comparisons,list) or not evidence.get("allAlternativesScanned"):
            return None
        bad=[x for x in comparisons if x.get("status") not in GUARD_STATUSES]
        if bad:
            return {"gate":gate,"reason":"PASS_WITH_UNDEFEATED_DIRECT_CHALLENGER",
                    "challengers":[{"id":x.get("challengerId"),"status":x.get("status")}
                                   for x in bad]}
    elif gate=="G17":
        counter=evidence.get("counterevidence") or {}
        if (evidence.get("sourceDerivedReviewResolved") is False or
            counter.get("unresolved") is True):
            return {"gate":gate,"reason":"PASS_WITH_UNRESOLVED_SOURCE_CONTRADICTION",
                    "sourceType":counter.get("sourceType")}
    elif gate=="Step8":
        if evidence.get("actualShiftByShiftObserved") is False:
            return {"gate":gate,"reason":"PASS_WITHOUT_OBSERVED_DEFENSIVE_SHIFTS"}
    return None

def _clock(value):
    if not value:
        return None
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d if d.tzinfo else None
    except ValueError:
        return None

def _pregame_anchored(row, leg, sources):
    measured=_clock(row["evaluated_at"])
    puck=_clock(leg.get("startUTC"))
    return bool(measured and puck and measured<=puck and
        sources and all(isinstance(s,str) and s.startswith("https://") for s in sources))

def _policy_guard_is_valid(gate, proof):
    if not proof:
        return False
    if gate=="G10.5":
        return contradiction(gate,{"allAlternativesScanned":True,
                  "comparisonRows":[{"challengerId":"test","status":"RIVAL_DOMINATES"}]}) is not None and contradiction(
                      gate,{"allAlternativesScanned":True,
                       "comparisonRows":[{"challengerId":"test","status":"DEFEATED"}]}) is None
    if gate=="G17":
        return contradiction(gate,{"sourceDerivedReviewResolved":False}) is not None and contradiction(
            gate,{"sourceDerivedReviewResolved":True,
                  "counterevidence":{"unresolved":False}}) is None
    if gate=="Step8":
        return contradiction(gate,{"actualShiftByShiftObserved":False}) is not None and contradiction(
            gate,{"actualShiftByShiftObserved":True}) is None
    return False

def active_guards(con, slate_date):
    """Read only previously validated, strictly earlier slate activations."""
    try:
        rows=con.execute("SELECT patch_id,policy,validation FROM patches").fetchall()
    except Exception:
        return {}
    guards={}
    for r in rows:
        try:
            policy=json.loads(r["policy"]);validation=json.loads(r["validation"])
        except (TypeError,ValueError):
            continue
        gate=policy.get("gate")
        if (GUARD_POLICIES.get(gate)==r["patch_id"] and
            validation.get("guardReplayTriggered") is True and
            validation.get("safeControlRejected") is False and
            validation.get("sourcedPregameContradiction") is True and
            policy.get("activatedAfterSlate","9999-99-99")<slate_date):
            guards[gate]=r["patch_id"]
    return guards

def apply_active_guards(candidate,traces,guards):
    """Executable future-run patch: exclude only an actual contradictory PASS.

    No new weights, no scorer selection, no conversion of absent evidence to PASS.
    The G18 record becomes a source-attributed elimination; the old card
    and its historical pregame gate matrix are untouched.
    """
    if not guards:
        return candidate,traces,[]
    fired=[]
    by_gate={x["gate"]:x for x in traces}
    for gate,patch in guards.items():
        r=by_gate.get(gate)
        if not r or r["disposition"]!="PASS":
            continue
        proof=contradiction(gate,(r.get("details") or {}).get("evidence") or {})
        if not proof:
            continue
        proof["activatedPatchId"]=patch
        proof["sourceIds"]=list((r.get("details") or {}).get("sourceIds") or [])
        r["disposition"]="ELIMINATED"
        r["details"]["patchEnforcement"]=proof
        fired.append(proof)
    if fired:
        candidate["complete"]=False
        for row in traces:
            if row["gate"]=="G18":
                row["disposition"]="ELIMINATED"
                row["details"]["activatedPostgameGuards"]=fired
        candidate.setdefault("patchGuardRejections",[]).extend(fired)
    return candidate,traces,fired

def adjudicate_misses(con, slate_date):
    """Commit deterministic, source-auditable decisions for the original misses."""
    setup(con)
    card=get_card(con,slate_date)
    if not card or not card.get("grade"):
        return {"status":"AWAITING_OFFICIAL_FROZEN_GRADE","slateDate":slate_date,
                "activated":[],"decisions":[]}
    graded=con.execute("SELECT * FROM grades WHERE card_id=?",
                       (card["card_id"],)).fetchone()
    if not graded:
        raise ValueError("Official frozen card has no immutable grade receipt")
    official_sources=json.loads(graded["official_sources"])
    if not official_sources or not all(
            isinstance(u,str) and u.startswith(OFFICIAL) for u in official_sources):
        raise ValueError("Cannot adjudicate patches without official NHL scoring evidence")
    legs={ (str(l["gameId"]),str(l["playerId"])):l for l in card["current_legs"] }
    outcomes=json.loads(graded["legs"])
    decisions=[];activated=[]
    for outcome in outcomes:
        if outcome["result"]!="MISS":
            continue
        game_id,pid=str(outcome["gameId"]),str(outcome["playerId"])
        leg=legs.get((game_id,pid))
        if not leg:
            raise ValueError("Graded missed player does not belong to locked Core")
        # Prefer last pre-puck CONFIRMED gate trace over projected without
        # mutating either. Historical labels/recipients never get replayed.
        traces=con.execute("""SELECT gate,disposition,details,evaluated_at,stage
             FROM gates WHERE slate_date=? AND game_id=? AND player_id=?
             AND stage IN ('CONFIRMED','PROJECTED')""",
             (slate_date,game_id,pid)).fetchall()
        before=[x for x in traces if _clock(x["evaluated_at"]) and
                _clock(leg.get("startUTC")) and
                _clock(x["evaluated_at"])<=_clock(leg["startUTC"])]
        by_gate={}
        for stage in ("PROJECTED","CONFIRMED"):
            for row in before:
                if row["stage"]==stage:
                    by_gate[row["gate"]]=row
        applicable=[]
        for gate,patch_id in GUARD_POLICIES.items():
            row=by_gate.get(gate)
            if not row or row["disposition"]!="PASS":
                continue
            details,sources=_gate_data(row)
            defect=contradiction(gate,details)
            if not defect or not _pregame_anchored(row,leg,sources):
                continue
            if not _policy_guard_is_valid(gate,defect):
                continue
            applicable.append((gate,patch_id,defect,sources,row["stage"]))
        if not applicable:
            note={"cardId":card["card_id"],"slateDate":slate_date,
                  "gameId":game_id,"playerId":pid,
                  "status":"NO_CAUSALLY_PROVEN_PREGAME_GATE_DEFECT",
                  "outcome":"MISS","officialGoals":outcome["goals"],
                  "codeAutomaticallyChanged":False,
                  "reason":"A scoreless game alone is not contradictory pregame gate evidence.",
                  "officialSources":official_sources}
            decisions.append(note)
            with transaction(con):
                con.execute("""INSERT OR IGNORE INTO postgame_patch_decisions VALUES
                    (?,?,?,?,?,?,?,?)""",(slate_date,card["card_id"],game_id,pid,
                    "NONE","NO_PATCH_WARRANTED",encode(note),stamp()))
        for gate,patch_id,defect,sources,phase in applicable:
            decision={"cardId":card["card_id"],"slateDate":slate_date,
                "gameId":game_id,"playerId":pid,"gate":gate,
                "policyId":patch_id,"status":"AUTOMATIC_GUARD_ACTIVATED",
                "pregameSourceURLs":sources,"officialSources":official_sources,
                "frozenPregameStage":phase,
                "provedPreGameDecisionContradiction":defect,
                "outcomeWasNotUsedAsPatchProof":True,
                "futureOnly":True,"cardFingerprintUnchanged":card["fingerprint"],
                "noRetrospectiveScorerOverride":True}
            with transaction(con):
                con.execute("""INSERT OR IGNORE INTO postgame_patch_decisions VALUES
                    (?,?,?,?,?,?,?,?)""",
                    (slate_date,card["card_id"],game_id,pid,patch_id,
                     "AUTOMATIC_GUARD_ACTIVATED",encode(decision),stamp()))
                # Only a predefined, testable guard is allowed to activate;
                # never generate an unreviewed new formula or edit code.
                con.execute("""INSERT OR IGNORE INTO patches VALUES (?,?,?,?,?,?)""",(
                    patch_id,encode([gate]),
                    encode({"gate":gate,"activatedAfterSlate":slate_date,
                            "triggerCardId":card["card_id"],
                            "sourcedPregameEvidenceURLs":sources}),
                    encode({"module":"nhl_true_blender_engine.postgame_recalibration",
                            "callable":"apply_active_guards","changes":"future contradictory PASS becomes ELIMINATED",
                            "editsPythonSource":False}),
                    encode({"guardReplayTriggered":True,
                            "safeControlRejected":False,
                            "sourcedPregameContradiction":True,
                            "noOutcomeOnlyPatch":True}),stamp()))
            decisions.append(decision)
            activated.append(patch_id)
    return {"slateDate":slate_date,"status":"POSTGAME_PATCH_ADJUDICATED",
        "cardId":card["card_id"],"decisions":decisions,
        "activated":sorted(set(activated)),"missCount":sum(
            x.get("result")=="MISS" for x in outcomes),
        "noUnprovenRuleChange":True,
        "originalCardUntouched":True}

def season_history(con,season_start_year,through_date):
    """Graded cards from October of start year; up to three real slates/month."""
    setup(con)
    start=f"{season_start_year}-10-01"
    end=f"{season_start_year+1}-09-30"
    if through_date<start:raise ValueError("Season history ends before its tracking window")
    rows=con.execute("""SELECT g.slate_date,g.card_id,g.result,g.legs,
                g.official_sources,c.current_legs,c.fingerprint,c.revision
                FROM grades g JOIN cards c ON g.card_id=c.card_id
                WHERE g.slate_date BETWEEN ? AND ?
                ORDER BY g.slate_date,g.card_id""",
                (start,min(end,through_date))).fetchall()
    month=defaultdict(list);all_slates=[]
    for row in rows:
        graded=json.loads(row["legs"])
        legs=json.loads(row["current_legs"])
        source_urls=json.loads(row["official_sources"])
        scored={(str(x["gameId"]),str(x["playerId"])) for x in graded}
        saved={(str(x["gameId"]),str(x["playerId"])) for x in legs}
        if saved!=scored:
            raise ValueError("Season history official goals do not correspond to saved recipients")
        hits=sum(x["result"]=="HIT" for x in graded)
        verified=("WIN" if hits==len(legs) else "LOSS")
        if verified!=row["result"] or not source_urls:
            raise ValueError("Season history grade contradicts official frozen card")
        slate={"date":row["slate_date"],"cardId":row["card_id"],
            "originalFingerprint":row["fingerprint"],"revision":row["revision"],
            "result":verified,"hits":hits,"legs":len(legs),
            "officialSources":source_urls}
        month[row["slate_date"][:7]].append(slate)
        all_slates.append(slate)
    month_reports={}
    for key,items in sorted(month.items()):
        n=len(items)
        picks=([items[0]] if n==1 else [items[0],items[-1]] if n==2 else [
            items[0],items[n//2],items[-1]])
        month_reports[key]={
            "gradedSlatesAvailable":n,"recalibrationSample":picks,
            "sampleCount":len(picks),"wins":sum(x["result"]=="WIN" for x in items),
            "losses":sum(x["result"]=="LOSS" for x in items),
            "sampleSelection":"First, middle and last actually graded slates (up to three); no ungraded or fabricated slates",
            "sampleDoesNotReplaceFullGradeLedger":True}
    decisions=con.execute("""SELECT status,policy_id FROM postgame_patch_decisions
                WHERE slate_date BETWEEN ? AND ?""",(start,min(end,through_date))).fetchall()
    applied=sorted(set(x["policy_id"] for x in decisions if
                       x["status"]=="AUTOMATIC_GUARD_ACTIVATED"))
    total=sum(x["legs"] for x in all_slates)
    wins=sum(x["result"]=="WIN" for x in all_slates)
    result={
        "season":f"{season_start_year}-{str(season_start_year+1)[-2:]}",
        "trackingWindowStart":start,"throughDate":through_date,
        "officiallyGradedSlates":len(all_slates),
        "wins":wins,"losses":len(all_slates)-wins,
        "legHits":sum(x["hits"] for x in all_slates),
        "legOpportunities":total,
        "winDefinition":"ALL_ORIGINAL_CORE_LEGS_SCORE",
        "monthlyThreeSlateCalibration":month_reports,
        "allOfficialGrades":all_slates,
        "verifiedAutomaticGuardPatches":applied,
        "postgameDecisionsWritten":len(decisions),
        "source":"FROZEN_SQLITE_CARDS_PLUS_OFFICIAL_NHL_GOAL_GRADES",
        "noSelectionsOrRetroactiveGradesInvented":True}
    with transaction(con):
        con.execute("""INSERT INTO season_calibration_history VALUES (?,?,?,?)
            ON CONFLICT(season,as_of_date) DO UPDATE SET report=excluded.report,
            generated_at=excluded.generated_at""",
            (result["season"],through_date,encode(result),stamp()))
    return result
