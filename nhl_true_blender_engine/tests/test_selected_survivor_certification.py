"""The selection pool is examined; nonselected losses do not veto a verified Core."""
from nhl_true_blender_engine.engine import execute,MASTER,OVERLAY
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,snapshot_without_shifts,DATE
from scripts.publish_site_state import export_run

SHIFT="https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId%3D2026020300"
PBP="https://api-web.nhle.com/v1/gamecenter/2026020300/play-by-play"

def with_shift_proofs():
    slate=snapshot()
    for g in slate["games"]:
        cov=g["coverage"][g["away"]]["data"]
        cov["shiftSourceUrls"]=[SHIFT]
        cov["actualDefensiveShiftMatches"]=1
        cov["shiftByShift"]=[{
            "zone":"slot","gameId":"2026020300","eventId":"11",
            "period":1,"eventClock":"04:12",
            "defendingOnIcePlayerIds":["11","22","33"],
            "officialPlayByPlayUrl":PBP,"officialShiftChartUrl":SHIFT}]
    return slate

def test_three_certified_survivors_can_publish_while_other_players_fail(tmp_path):
    con=open_db(str(tmp_path/"selected.sqlite"))
    slate=with_shift_proofs()
    result=execute(con,slate,DATE,"CONFIRMED")
    assert result["card"] is not None,result["errors"]
    audit=certify_gates(con,DATE,"CONFIRMED",len(slate["games"]))
    assert audit["scannedSkaters"]==9
    assert audit["allSkatersHaveEachGateRecord"]
    assert audit["allSkatersHaveExactExecutionOrder"]
    assert audit["allOverlayStepsWereIndependentlyChecked"]
    assert len(audit["selectedLegs"])==3
    assert audit["selectedCoreOnlyFullyCertified"] is True
    assert audit["selectedSourceAttributionGaps"]==[]
    assert audit["fullIndependentCardCertification"] is True
    funnel=audit["selectionFunnel"]
    assert funnel["surveyedEligibleSkaters"]==9
    assert funnel["lockedCoreRecipients"]==3
    assert sum(v for k,v in funnel.items() if k in
          ("sourceEliminated","notQualifiedIncompleteEvidence",
           "qualifiedButNotChosen","otherNotSelected","lockedCoreRecipients"))==9
    assert funnel["sourceEliminated"]+funnel["notQualifiedIncompleteEvidence"]>=3
    assert audit["nonselectedCandidateFailuresAreNotCertificationErrors"] is True
    assert any(audit["masterGateDispositions"][g].get("ELIMINATED",0)>0
        or audit["masterGateDispositions"][g].get("NOT_EXECUTED",0)>0
        for g in MASTER)
    result["gateCertification"]=audit
    status=export_run(con,DATE,"CONFIRMED",result,tmp_path/"state")
    assert status["currentRunFullyCertified"] is True
    assert status["survivorOnlyCertification"] is True
    assert status["selectionFunnel"]["lockedCoreRecipients"]==3
    assert status["publicationDecision"]=="SOURCE_CERTIFIED_AND_PUBLISHED"
    assert status["publishedToSite"] is True
    assert (tmp_path/"state"/"site_cards"/(DATE+".json")).is_file()
    # The independent published-Core contract must accept this exact
    # verified single-pipeline receipt, not demand 36 duplicate gate rows.
    from nhl_true_blender_engine.dashboard_export import export_dashboard
    from scripts.verify_published_core import verify_published_core
    export_dashboard(con,DATE,"CONFIRMED",slate,tmp_path/"state")
    verified=verify_published_core(tmp_path/"state",DATE)
    assert verified["status"]=="ORIGINAL_G0_G18_CORE_VERIFIED"
    assert all(x["checks"]==len(MASTER) for x in verified["selected"])
    con.close()

def test_missing_selected_gate_is_real_failure_not_overridden_by_other_losses(tmp_path):
    con=open_db(str(tmp_path/"missing.sqlite"))
    # A required own-mechanism gap blocks new certification. Optional missing
    # shift metrics alone must not become an artificial scorer veto.
    from nhl_true_blender_engine.tests.test_live_gate_certification import missing_required_mechanism
    slate=missing_required_mechanism()
    result=execute(con,slate,DATE,"CONFIRMED")
    assert result["card"] is None
    audit=certify_gates(con,DATE,"CONFIRMED",len(slate["games"]))
    assert audit["allSkatersHaveEachGateRecord"] is True
    assert audit["selectedCoreOnlyFullyCertified"] is False
    assert audit["fullIndependentCardCertification"] is False
    assert audit["selectedLegs"]==[]
    assert audit["overlayGateDispositions"]["Step8"].get("NOT_EXECUTED",0)>0
    result["gateCertification"]=audit
    status=export_run(con,DATE,"CONFIRMED",result,tmp_path/"state")
    assert status["currentRunFullyCertified"] is False
    assert status["publishedToSite"] is False
    assert status["publicationDecision"]=="NO_ELIGIBLE_G18_CARD"
    con.close()


def test_post_puck_run_does_not_unpublish_frozen_verified_core(tmp_path):
    con=open_db(str(tmp_path/"postpuck.sqlite"))
    slate=with_shift_proofs()
    original=execute(con,slate,DATE,"CONFIRMED")
    original["gateCertification"]=certify_gates(con,DATE,"CONFIRMED",3)
    root=tmp_path/"state"
    first=export_run(con,DATE,"CONFIRMED",original,root)
    assert first["publishedToSite"] is True
    card_file=root/"site_cards"/(DATE+".json")
    before=card_file.read_bytes()
    # Later run cannot issue a NEW card because the matches have started.
    # The still-saved card is not a new selection or automatically changed.
    postpuck={"card":None,"games":3,"g0Directions":6,"gateRows":original["gateRows"],
              "eligibleSkaterRows":original["eligibleSkaterRows"],
              "gateCertification":certify_gates(con,DATE,"CONFIRMED",3),
              "errors":[]}
    saved=export_run(con,DATE,"CONFIRMED",postpuck,root)
    assert card_file.read_bytes()==before
    assert saved["cardId"]==first["cardId"]
    assert saved["publishedToSite"] is True
    assert saved["retainedOriginalLockedCard"] is True
    assert saved["currentRunFullyCertified"] is True
    assert saved["publicationDecision"]=="PRESERVED_FROZEN_CORE_NO_NEW_SELECTION"
    con.close()


def test_source_verified_core_remains_published_without_falsely_certifying_unresolved_slate(tmp_path):
    """Unresolved other-game G0 never deletes the original 3, nor turns the run green."""
    con=open_db(str(tmp_path/"partial.sqlite"))
    slate=with_shift_proofs()
    result=execute(con,slate,DATE,"CONFIRMED")
    assert result["card"] is not None and not result["errors"]
    result["gateCertification"]=certify_gates(con,DATE,"CONFIRMED",3)
    # A genuine collector-level error outside the already-proven original
    # recipients is still an unfinished *full slate* research obligation.
    result["errors"].append(
        "other-game G0 source consensus exists but multiple projected goalies remain")
    root=tmp_path/"state"
    status=export_run(con,DATE,"CONFIRMED",result,root)
    assert status["selectedCoreFullyCertified"] is True
    assert status["currentRunFullyCertified"] is False
    assert status["publishedToSite"] is True
    assert status["cardSavedByEngine"] is True
    assert status["publicationDecision"]=="CORE_PUBLISHED_WITH_UNRESOLVED_SLATE_EVIDENCE"
    assert (root/"site_cards"/(DATE+".json")).is_file()
    # Independently verify all selected original G0-G18 receipts even though
    # another game's G0 remains unresolved: never a fake full-slate success.
    from nhl_true_blender_engine.dashboard_export import export_dashboard
    from scripts.verify_published_core import verify_published_core
    export_dashboard(con,DATE,"CONFIRMED",slate,root)
    validated=verify_published_core(root,DATE)
    assert validated["status"]=="ORIGINAL_G0_G18_CORE_VERIFIED"
    con.close()

