"""The selection pool is examined; nonselected losses do not veto a verified Core."""
from nhl_true_blender_engine.engine import execute,MASTER,OVERLAY
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE
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
    con.close()

def test_missing_selected_gate_is_real_failure_not_overridden_by_other_losses(tmp_path):
    con=open_db(str(tmp_path/"missing.sqlite"))
    slate=snapshot() # deliberately no source-backed shift events
    result=execute(con,slate,DATE,"CONFIRMED")
    audit=certify_gates(con,DATE,"CONFIRMED",len(slate["games"]))
    assert audit["allSkatersHaveEachGateRecord"] is True
    assert audit["selectedCoreOnlyFullyCertified"] is False
    assert audit["fullIndependentCardCertification"] is False
    assert all(not x["overlayAllPass"] for x in audit["selectedLegs"])
    result["gateCertification"]=audit
    status=export_run(con,DATE,"CONFIRMED",result,tmp_path/"state")
    assert status["currentRunFullyCertified"] is False
    assert status["publishedToSite"] is False
    assert status["publicationDecision"]=="NEW_CARD_NOT_PUBLISHED_INCOMPLETE_OVERLAY"
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
