"""A full 4,150-row matrix is not an independent evidence pass certificate."""
import json
from nhl_true_blender_engine.engine import execute,MASTER,OVERLAY
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,snapshot_without_shifts,DATE
from scripts.publish_site_state import export_run

def missing_required_mechanism():
    slate=snapshot_without_shifts()
    for game in slate['games']:
        for p in game['rosters'][game['away']]['data']['players']:
            p['release']['data']['archetype']='OBSERVED_OWN_SHOT_ORIGIN'
    return slate

def test_census_separates_gate_row_count_from_real_source_proof(tmp_path):
    con=open_db(str(tmp_path/"ledger.sqlite"))
    s=missing_required_mechanism()
    result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"] is None
    audit=certify_gates(con,DATE,"CONFIRMED",len(s["games"]))
    assert audit["allSkatersHaveEachGateRecord"] is True
    assert audit["allSkatersHaveExactExecutionOrder"] is True
    assert audit["allOverlayStepsWereIndependentlyChecked"] is True
    assert audit["gateRows"]==9*len(MASTER)+6
    assert audit["selectedMasterGatesAllPass"] is False
    assert audit["selectedOverlayGatesAllPass"] is False
    assert audit["selectedLegs"]==[]  # no provisional Core saved
    assert audit["fullIndependentCardCertification"] is False
    assert audit["overlayGateDispositions"]["Step8"]["NOT_EXECUTED"]>0
    con.close()

def test_unproven_independent_overlay_cannot_newly_publish_card(tmp_path):
    con=open_db(str(tmp_path/"ledger.sqlite"))
    s=missing_required_mechanism();result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"] is None
    result["gateCertification"]=certify_gates(con,DATE,"CONFIRMED",3)
    status=export_run(con,DATE,"CONFIRMED",result,tmp_path/"state")
    assert status["publishedToSite"] is False
    assert status["currentRunFullyCertified"] is False
    assert status["publicationDecision"]=="NO_ELIGIBLE_G18_CARD"
    assert not (tmp_path/"state"/"site_cards"/(DATE+".json")).exists()
    con.close()

def test_locked_original_card_survives_later_independent_source_gap(tmp_path):
    con=open_db(str(tmp_path/"ledger.sqlite"))
    s=snapshot();result=execute(con,s,DATE,"CONFIRMED")
    assert result["card"] is not None
    # A later regression must not rewrite a previously locked original.
    con.execute("""UPDATE gates SET disposition='NOT_EXECUTED'
        WHERE slate_date=? AND stage='CONFIRMED' AND player_id='1010'
              AND gate='G9'""",(DATE,))
    con.commit()
    result["gateCertification"]=certify_gates(con,DATE,"CONFIRMED",3)
    saved=result["card"];card_dir=tmp_path/"state"/"site_cards"
    card_dir.mkdir(parents=True,exist_ok=True)
    stored={"cardId":saved["card_id"],"fingerprint":saved["fingerprint"],
            "status":"G18_SOURCE_VERIFIED","verified":True,
            "revision":saved["revision"],"stage":saved["stage"],
            "legsJson":json.dumps(saved["current_legs"])}
    path=card_dir/(DATE+".json")
    path.write_text(json.dumps(stored))
    before=path.read_bytes()
    status=export_run(con,DATE,"CONFIRMED",result,tmp_path/"state")
    assert path.read_bytes()==before
    assert status["retainedOriginalLockedCard"] is True
    assert status["currentRunFullyCertified"] is False
    assert status["publicationDecision"]=="PRESERVED_ORIGINAL_WITH_AUDIT_GAPS"
    assert any("G9" in x["notPassing"] for x in status["independentOverlaySourceGaps"])
    con.close()

