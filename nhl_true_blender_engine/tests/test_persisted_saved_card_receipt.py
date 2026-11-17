"""A failed current research pass cannot erase earlier real, source-proven G18 receipts."""
import json
from pathlib import Path
import shutil

from scripts.preserved_core_receipt import verified_original_receipt

ROOT=Path(__file__).resolve().parents[2]
DATE="2026-11-17"


def fixture(tmp_path):
    for sub in ("site_cards","site_gates","site_runs","core_retractions"):
        (tmp_path/sub).mkdir()
        src=ROOT/"state"/sub/(DATE+".json")
        if src.exists():
            shutil.copy2(src,tmp_path/sub/src.name)
    return json.loads((tmp_path/"site_cards"/(DATE+".json")).read_text())


def test_saved_revised_core_survives_newer_research_failure(tmp_path):
    card=fixture(tmp_path)
    run=json.loads((tmp_path/"site_runs"/(DATE+".json")).read_text())
    assert run["currentRunFullyCertified"] is False
    assert run["publishedToSite"] is False
    assert card["fingerprint"]!=json.loads(
        (tmp_path/"core_retractions"/(DATE+".json")).read_text())["originalFingerprint"]
    matrix=verified_original_receipt(tmp_path,DATE,card)
    assert matrix is not None
    assert {x["playerId"] for x in matrix["legs"]}=={
        x["playerId"] for x in json.loads(card["legsJson"])}
    assert all(x["masterPassed"]==20 and x["overlayPassed"]==16
               for x in matrix["legs"])


def test_revoked_original_cannot_be_resurrected(tmp_path):
    card=fixture(tmp_path)
    tombstone=json.loads((tmp_path/"core_retractions"/(DATE+".json")).read_text())
    card["fingerprint"]=tombstone["originalFingerprint"]
    assert verified_original_receipt(tmp_path,DATE,card) is None


def test_forged_full_gate_pass_missing_source_or_time_is_rejected(tmp_path):
    card=fixture(tmp_path)
    f=tmp_path/"site_gates"/(DATE+".json")
    original=json.loads(f.read_text())
    row=original["legs"][0]["gateDetails"][9]
    assert row["gate"]=="G9"
    row["sourceIds"]=[]
    f.write_text(json.dumps(original))
    assert verified_original_receipt(tmp_path,DATE,card) is None
    original["legs"][0]["gateDetails"][9]["sourceIds"]=[
       "https://api-web.nhle.com/v1/gamecenter/2026020300/play-by-play"]
    original["legs"][0]["gateDetails"][9]["evaluatedAt"]="2099-11-17T13:00:00Z"
    f.write_text(json.dumps(original))
    assert verified_original_receipt(tmp_path,DATE,card) is None


def test_wrong_card_or_missing_gate_trace_cannot_unlock_ui(tmp_path):
    card=fixture(tmp_path)
    assert verified_original_receipt(tmp_path,DATE,{**card,"verified":False}) is None
    assert verified_original_receipt(tmp_path,DATE,{**card,"fingerprint":"made-up"}) is None
    f=tmp_path/"site_gates"/(DATE+".json")
    matrix=json.loads(f.read_text())
    matrix["legs"][1]["gateDetails"].pop(11)
    f.write_text(json.dumps(matrix))
    assert verified_original_receipt(tmp_path,DATE,card) is None


def test_deployment_refresh_cannot_overwrite_an_independently_proven_gate_export(tmp_path, monkeypatch):
    from nhl_true_blender_engine.storage import open_db
    import scripts.refresh_selected_gate_exports as module
    card=fixture(tmp_path)
    gate_path=tmp_path/"site_gates"/(DATE+".json")
    original=gate_path.read_bytes()
    assert verified_original_receipt(tmp_path,DATE,card) is not None
    db=open_db(str(tmp_path/"true_blender.sqlite"))
    db.close()

    def prevent_later_review_replacing_proven_receipt(*args,**kwargs):
        raise AssertionError("A weaker or newer read-only reconstruction must not replace original source proof")

    monkeypatch.setattr(module,"export_dashboard",prevent_later_review_replacing_proven_receipt)
    outcome=module.refresh(tmp_path)
    assert gate_path.read_bytes()==original
    assert verified_original_receipt(tmp_path,DATE,card) is not None
    assert any(x["date"]==DATE and
        x["reason"]=="PREVIOUS_INDEPENDENT_CERTIFIED_PREPUCK_RECEIPT"
        for x in outcome["preserved"])
