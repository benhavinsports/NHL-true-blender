"""The UI must show real selected-player gate receipts, never invented PASSes."""
import json
from nhl_true_blender_engine.engine import execute,MASTER,OVERLAY,EXECUTION_ORDER
from nhl_true_blender_engine.storage import open_db,get_card
from nhl_true_blender_engine.dashboard_export import export_dashboard
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE

def test_dashboard_exports_one_saved_core_real_36_checks_and_all_games(tmp_path):
    con=open_db(str(tmp_path/"ledger.sqlite"))
    slate=snapshot(3)
    result=execute(con,slate,DATE,"CONFIRMED")
    assert result["card"] is not None,result["errors"]
    before=get_card(con,DATE)
    metrics=export_dashboard(con,DATE,"CONFIRMED",slate,tmp_path/"state")
    doc=json.loads((tmp_path/"state"/"site_gates"/f"{DATE}.json").read_text())
    assert metrics["cardId"]==before["card_id"]
    assert doc["cardId"]==before["card_id"]
    assert doc["fingerprint"]==before["fingerprint"]
    assert doc["revision"]==before["revision"]
    assert doc["readOnly"] is True
    assert doc["doesNotSelectOrReplaceScorers"] is True
    assert len(doc["games"])==3
    assert len(doc["legs"])==3
    assert {x["playerId"] for x in doc["legs"]}=={
         str(l["playerId"]) for l in before["current_legs"]}
    for selected in doc["legs"]:
        assert len(selected["gateDetails"])==36
        assert [g["gate"] for g in selected["gateDetails"]]==EXECUTION_ORDER
        assert selected["executionOrderVerified"] is True
        assert selected["gateDetails"][-1]["gate"]=="G18"
        assert selected["masterPassed"]==20
        # A complete synthetic defensive-shift receipt can prove Step8.
        assert selected["overlayPassed"]==16
        assert selected["sourceVerifiedPregameGateCount"]==(
            selected["masterPassed"]+selected["overlayPassed"])
        assert selected["gateDetails"][EXECUTION_ORDER.index("G10.5")]["gate"]=="G10.5"
        assert selected["gateDetails"][30]["gate"]=="Step10.5"
        assert all(g["prePuckRecord"] for g in selected["gateDetails"])
        assert selected["gateDetails"][0]["sourceIds"]
        assert selected["gateDetails"][0]["evidence"]["targetGoalie"]
    assert get_card(con,DATE)==before
    con.close()

def test_post_puck_gate_update_is_not_passed_off_as_original_evidence(tmp_path):
    con=open_db(str(tmp_path/"frozen.sqlite"))
    slate=snapshot(3)
    result=execute(con,slate,DATE,"CONFIRMED")
    card=result["card"]
    leg=card["current_legs"][0]
    con.execute("""UPDATE gates SET evaluated_at=?
        WHERE slate_date=? AND stage=? AND game_id=? AND player_id=? AND gate=?""",
        ("2099-01-01T12:00:00Z",DATE,"CONFIRMED",leg["gameId"],leg["playerId"],"G0"))
    export_dashboard(con,DATE,"CONFIRMED",slate,tmp_path/"state")
    report=json.loads((tmp_path/"state"/"site_gates"/f"{DATE}.json").read_text())
    selected=next(x for x in report["legs"] if x["playerId"]==str(leg["playerId"]))
    first=selected["gateDetails"][0]
    assert first["gate"]=="G0"
    assert first["status"]=="NO_PREPUCK_RECEIPT"
    assert first["sourceIds"]==[]
    assert first["prePuckRecord"] is False
    assert selected["masterPassed"]==19
    assert get_card(con,DATE)["card_id"]==card["card_id"]
    con.close()
