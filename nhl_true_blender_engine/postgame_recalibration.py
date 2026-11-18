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


def _original_slate_gate_proof(root, slate_date, card, leg):
    """Read actual immutable selected-card evidence, never stitch multiple runs.

    A saved original projected receipt is superior to whichever current gate
    matrix happened to survive after confirmation/grade. Identity, the
    original saved order, timestamps and provenance must match the frozen card.
    """
    if root is None:
        return None
    from pathlib import Path
    from .engine import MASTER, OVERLAY, EXECUTION_ORDER

    root=Path(root)
    original=root/"site_gates"/f"{slate_date}-original-projected.json"
    current=root/"site_gates"/f"{slate_date}.json"
    old_order=list(MASTER[:-1])+list(OVERLAY)+["G18"]
    expected={(str(x["gameId"]),str(x["playerId"]))
              for x in card["current_legs"]}
    for path in (original,current):
        if not path.is_file():
            continue
        try:
            snapshot=json.loads(path.read_text(encoding="utf-8"))
            if (snapshot.get("cardId")!=card["card_id"]
                    or snapshot.get("fingerprint")!=card["fingerprint"]
                    or snapshot.get("revision")!=card["revision"]
                    or snapshot.get("readOnly") is not True
                    or snapshot.get("doesNotSelectOrReplaceScorers") is not True):
                continue
            legs=snapshot.get("legs") or []
            if {(str(x["gameId"]),str(x["playerId"])) for x in legs}!=expected:
                continue
            order=snapshot.get("executionOrder")
            if order!=EXECUTION_ORDER and order!=old_order:
                continue
            proof={}
            for selected in legs:
                trace=selected.get("gateDetails") or []
                start=_clock(selected.get("startUTC"))
                if (not start or len(trace)!=len(order)
                        or selected.get("executionOrderVerified") is not True):
                    break
                entries={}
                for idx, row in enumerate(trace):
                    observed=_clock(row.get("evaluatedAt"))
                    sources=row.get("sourceIds") or []
                    if (row.get("gate")!=order[idx]
                            or not observed or observed>=start
                            or row.get("prePuckRecord") is not True
                            or row.get("recordedExecutionIndex")!=idx
                            or row.get("expectedExecutionIndex")!=idx
                            or row.get("executionOrderVerified") is not True
                            or not all(isinstance(url,str)
                                and url.startswith("https://") for url in sources)):
                        break
                    entries[row["gate"]]={
                        "stage":selected.get("stageOfGateRecords") or
                                 snapshot.get("savedOriginalStage") or
                                 snapshot.get("stage"),
                        "evaluated_at":row["evaluatedAt"],
                        "disposition":row.get("status"),
                        "details":encode({"evidence":row.get("evidence") or {},
                                          "sourceIds":sources})
                    }
                if len(entries)!=len(order):
                    break
                proof[(str(selected["gameId"]),str(selected["playerId"]))]=entries
            if len(proof)!=len(expected):
                continue
            selected=proof.get((str(leg["gameId"]),str(leg["playerId"])))
            if selected:
                return selected,{"receiptType":"ORIGINAL_COMMITTED_SOURCE_GATE_EXPORT",
                                  "file":path.name,
                                  "stage":next(iter(selected.values()))["stage"],
                                  "individualOrderedChecks":len(order),
                                  "cardFingerprintMatched":True,
                                  "noMixedGateRuns":True}
        except (OSError,ValueError,TypeError,KeyError):
            continue
    return None


def _stored_pregame_gate_proof(con, slate_date, leg):
    """Prefer a coherent timestamped original gate cohort over mixed rows."""
    from .engine import MASTER, OVERLAY, EXECUTION_ORDER

    puck=_clock(leg.get("startUTC"))
    if not puck:
        return {},{"receiptType":"MISSING_PUCK_DROP_TIME"}
    args=(slate_date,str(leg["gameId"]),str(leg["playerId"]))
    active=con.execute("""SELECT stage,gate,disposition,details,evaluated_at
        FROM gates WHERE slate_date=? AND game_id=? AND player_id=?
        AND stage IN ('PROJECTED','CONFIRMED')""",args).fetchall()
    archived=con.execute("""SELECT stage,gate,disposition,details,evaluated_at
        FROM gate_history WHERE slate_date=? AND game_id=? AND player_id=?
        AND stage IN ('PROJECTED','CONFIRMED')""",args).fetchall()
    groups={}
    for origin,rows in (("CURRENT",active),("HISTORY",archived)):
        for row in rows:
            at=_clock(row["evaluated_at"])
            if at and at<puck:
                groups.setdefault((origin,row["stage"],row["evaluated_at"]),[]).append(row)
    legacy=list(MASTER[:-1])+list(OVERLAY)+["G18"]
    coherent=[]
    for (origin,stage,when),rows in groups.items():
        by_gate={row["gate"]:row for row in rows}
        for order in (EXECUTION_ORDER,legacy):
            if len(rows)!=len(order) or len(by_gate)!=len(order):
                continue
            if set(by_gate)!=set(order):
                continue
            if all(json.loads(by_gate[g]["details"]).get("executionIndex")==idx
                   for idx,g in enumerate(order)):
                coherent.append((stage,when,origin,by_gate))
                break
    if coherent:
        # Preserve the initial projected selection when its historical
        # matrix exists; never build a synthetic 36/36 from separate runs.
        coherent.sort(key=lambda x:(x[0]!="PROJECTED",x[1]),reverse=False)
        stage,when,origin,rows=coherent[0]
        return rows,{"receiptType":"SAME_EXECUTION_DATABASE_GATE_COHORT",
                     "stage":stage,"evaluatedAt":when,"databaseOrigin":origin,
                     "individualOrderedChecks":len(rows),"noMixedGateRuns":True}
    # Legacy standalone test/diagnostic records can still be inspected, but
    # explicitly mark that their complete execution is NOT certified.
    by_gate={}
    for stage in ("PROJECTED","CONFIRMED"):
        for row in active:
            if row["stage"]==stage and _clock(row["evaluated_at"]) and (
                    _clock(row["evaluated_at"])<puck):
                by_gate[row["gate"]]=row
    return by_gate,{"receiptType":"PARTIAL_CURRENT_DATABASE_RECORDS",
                    "individualOrderedChecks":len(by_gate),
                    "noMixedGateRuns":False,
                    "fullOriginalMatrixRecovered":False}


def _audit_original_gate_proof(con, slate_date, card, leg, root):
    original=_original_slate_gate_proof(root,slate_date,card,leg)
    if original is not None:
        return original
    return _stored_pregame_gate_proof(con,slate_date,leg)

def _verified_recipient_audit(card, slate_date, root, supplied):
    """Return only the official scorer comparison tied to this exact frozen card."""
    if supplied is None and root is not None:
        from pathlib import Path
        path=Path(root)/"site_runs"/f"{slate_date}-recipient-audit.json"
        try:
            supplied=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            supplied=None
    if not isinstance(supplied,dict):
        return None
    expected={(str(x["gameId"]),str(x["playerId"])) for x in card["current_legs"]}
    rows=supplied.get("selectedLegs") or []
    actual={(str(x.get("gameId")),str(x.get("lockedPlayerId"))) for x in rows}
    urls=supplied.get("officialSourceUrls") or []
    if (supplied.get("status")!="OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON"
            or supplied.get("cardId")!=card["card_id"]
            or supplied.get("originalFingerprint")!=card["fingerprint"]
            or supplied.get("originalRevision")!=card["revision"]
            or actual!=expected or len(rows)!=len(expected)
            or not urls or not all(isinstance(x,str) and x.startswith(OFFICIAL) for x in urls)):
        return None
    return {(str(x["gameId"]),str(x["lockedPlayerId"])):x for x in rows}


def _recipient_review_signals(item):
    """Translate postgame anomalies into review targets, never automatic picks or patches."""
    if not isinstance(item,dict):
        return None
    flags=set(item.get("auditFlags") or [])
    targets=[]
    scorer_rows=[]
    if "SCORING_TEAMMATE_WAS_PREGAME_G105_DEFEATED_RETROSPECTIVELY" in flags:
        targets.append("G10.5")
        scorer_rows=[{
            "player":x.get("player"),"playerId":x.get("playerId"),
            "goals":x.get("goals"),"pregameG105Verdict":x.get("pregameG105Verdict"),
            "pregameG105ChallengerEvidence":x.get("pregameG105ChallengerEvidence"),
            "reasonNotPregameG105Compared":x.get("reasonNotPregameG105Compared")
        } for x in item.get("officialScorers",[])
          if x.get("sameAttackDirectionAsCore") is True
          and x.get("goals",0)>0
          and x.get("pregameG105Verdict")=="DEFEATED"]
    if ("OPPOSITE_G0_DIRECTION_SCORED_MORE_POSTGAME_ONLY" in flags or
            "OPPOSING_G0_ATTACK_DIRECTION_NOT_COMPLETELY_SOURCE_REVIEWED" in flags):
        targets.append("G0")
    if "ORIGINAL_G10_FUTURE_FEEDER_ROLE_WAS_OVERCLAIMED" in flags:
        targets.append("G10")
    if "ORIGINAL_G15_WAS_NOT_INDEPENDENT_FINISHER_PROOF" in flags:
        targets.append("G15")
    if not targets:
        return None
    gate_order=("G0","G1","G2","G3","G4","G5","G6","G7","G8","G9",
                "G10","G10.5","G11","G12","G13","G14","G15","G16","G17")
    ordered_targets=[g for g in gate_order if g in set(targets)]
    return {
        "status":"PREGAME_GATE_REPLAY_REQUIRED",
        "reviewTargets":ordered_targets,
        "postgameSignals":sorted(flags),
        "lockedPlayer":item.get("lockedPlayer"),
        "lockedPlayerId":item.get("lockedPlayerId"),
        "sameAttackSideGoals":item.get("sameAttackSideGoals"),
        "oppositeAttackSideGoals":item.get("oppositeAttackSideGoals"),
        "officialScorersMarkedDefeated":scorer_rows,
        "pregameBothG0Directions":item.get("pregameBothG0Directions"),
        "prePuckGateReceipts":item.get("prePuckGateReceipts"),
        "postgameOutcomesAreReviewTriggersNotPregameProof":True,
        "doesNotSelectOrRecommendAnAlternative":True,
        "doesNotActivateAPatchByItself":True
    }


def adjudicate_misses(con, slate_date, root=None, recipient_audit=None):
    """Commit source-auditable miss decisions and preserve unresolved replay signals."""
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
    recipient_rows=_verified_recipient_audit(card,slate_date,root,recipient_audit)
    decisions=[];activated=[]
    for outcome in outcomes:
        if outcome["result"]!="MISS":
            continue
        game_id,pid=str(outcome["gameId"]),str(outcome["playerId"])
        leg=legs.get((game_id,pid))
        if not leg:
            raise ValueError("Graded missed player does not belong to locked Core")
        # Audit the actual locked original source matrix first, followed by
        # coherent historical DB cohorts. Never treat the latest confirmation
        # diagnostic as the only available pre-puck evidence.
        by_gate,gate_provenance=_audit_original_gate_proof(
            con,slate_date,card,leg,root)
        recipient_item=(recipient_rows or {}).get((game_id,pid))
        review_signal=_recipient_review_signals(recipient_item)
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
            review_required=bool(review_signal)
            note={"cardId":card["card_id"],"slateDate":slate_date,
                  "gameId":game_id,"playerId":pid,
                  "status":("PREGAME_GATE_REPLAY_REQUIRED" if review_required
                            else "NO_CAUSALLY_PROVEN_PREGAME_GATE_DEFECT"),
                  "outcome":"MISS","officialGoals":outcome["goals"],
                  "codeAutomaticallyChanged":False,
                  "gateAuditProvenance":gate_provenance,
                  "reason":("Official scorer comparison exposed a contradiction signal; "
                            "the original gate evidence must be replayed before ruling "
                            "out a defect." if review_required else
                            "No source-backed pregame contradiction was established."),
                  "recipientAuditReview":review_signal,
                  "outcomeWasNotUsedAsPatchProof":True,
                  "officialSources":official_sources}
            decisions.append(note)
            with transaction(con):
                con.execute("""INSERT OR IGNORE INTO postgame_patch_decisions VALUES
                    (?,?,?,?,?,?,?,?)""",(slate_date,card["card_id"],game_id,pid,
                    "NONE","REVIEW_REQUIRED" if review_required else "NO_PATCH_WARRANTED",
                    encode(note),stamp()))
        for gate,patch_id,defect,sources,phase in applicable:
            decision={"cardId":card["card_id"],"slateDate":slate_date,
                "gameId":game_id,"playerId":pid,"gate":gate,
                "policyId":patch_id,"status":"AUTOMATIC_GUARD_ACTIVATED",
                "pregameSourceURLs":sources,"officialSources":official_sources,
                "gateAuditProvenance":gate_provenance,
                "frozenPregameStage":phase,
                "provedPreGameDecisionContradiction":defect,
                "recipientAuditReview":review_signal,
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


def official_route_calibration(root, frozen_cards):
    """Aggregate verified postgame G0/G10.5 errors without hindsight selection.

    Counts only signed-by-card-identity official recipient-audit receipts.
    The counters are observations, NOT weights, new gates or future filters.
    """
    from pathlib import Path
    report={
        "source":"PRESERVED_ORIGINAL_CORES_PLUS_OFFICIAL_NHL_SCORER_COMPARISONS",
        "officiallyComparedSlates":0,
        "originalLegsCompared":0,
        "scorerMissesCompared":0,
        "missesWithDefeatedTeammateScorer":0,
        "missesWithOppositeG0SideScoringMore":0,
        "observations":[],
        "postgameOutcomesAreNotPregamePatchProof":True,
        "noOddsWeightsOrAutomaticRecipientOverride":True,
    }
    if root is None:
        return report
    root=Path(root)
    for saved in frozen_cards:
        date=saved["date"]
        path=root/"site_runs"/f"{date}-recipient-audit.json"
        if not path.is_file():
            continue
        try:
            audit=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            continue
        recipients=saved["recipients"]
        rows=audit.get("selectedLegs") or []
        identities={(str(x.get("gameId")),str(x.get("lockedPlayerId")))
                    for x in rows}
        if (audit.get("status")!="OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON"
                or audit.get("cardId")!=saved["cardId"]
                or audit.get("originalFingerprint")!=saved["fingerprint"]
                or audit.get("originalRevision")!=saved["revision"]
                or identities!=recipients or len(rows)!=len(recipients)
                or not audit.get("officialSourceUrls")
                or not all(isinstance(url,str)
                    and url.startswith("https://api-web.nhle.com/v1/")
                    for url in audit["officialSourceUrls"])):
            continue
        report["officiallyComparedSlates"]+=1
        report["originalLegsCompared"]+=len(rows)
        for item in rows:
            goals=item.get("chosenGoals")
            same=item.get("sameAttackSideGoals")
            other=item.get("oppositeAttackSideGoals")
            if type(goals) is not int or goals<0:
                continue
            if goals>0:
                continue
            rivals=[{
                "player":s.get("player"),"playerId":s.get("playerId"),
                "goals":s.get("goals")}
                for s in item.get("officialScorers",[])
                if s.get("sameAttackDirectionAsCore") is True
                and s.get("pregameG105Verdict")=="DEFEATED"
                and type(s.get("goals")) is int and s["goals"]>0]
            opposite=bool(type(same) is int and type(other) is int
                          and other>same)
            report["scorerMissesCompared"]+=1
            if rivals:
                report["missesWithDefeatedTeammateScorer"]+=1
            if opposite:
                report["missesWithOppositeG0SideScoringMore"]+=1
            report["observations"].append({
                "slateDate":date,"gameId":item.get("gameId"),
                "playerId":item.get("lockedPlayerId"),
                "originalPlayer":item.get("lockedPlayer"),
                "originalPath":item.get("lockedPath"),
                "G0selectedSide":item.get("lockedTeam"),
                "sameAttackSideGoals":same,
                "oppositeAttackSideGoals":other,
                "oppositeSideScoredMore":opposite,
                "G10_5DefeatedTeammatesWhoScored":rivals,
                "officialSourceUrls":item.get("officialSources") or [],
                "calibrationOnlyNoCausalRuleClaim":True,
            })
    return report


def season_history(con,season_start_year,through_date,root=None):
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
    month=defaultdict(list);all_slates=[];frozen_cards=[]
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
        frozen_cards.append({
            "date":row["slate_date"],"cardId":row["card_id"],
            "fingerprint":row["fingerprint"],"revision":row["revision"],
            "recipients":saved})
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
        "officialRouteCalibration":official_route_calibration(root,frozen_cards),
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
