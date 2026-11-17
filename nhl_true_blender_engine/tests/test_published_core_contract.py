"""Acceptance checks use ACTUAL original gate execution, not 36 fabricated rows.

Synthetic NHL input is processed by the same engine, census, publisher and
dashboard exporter that produce an official saved Core. No real picks changed.
"""
import json
import pytest

from nhl_true_blender_engine.engine import execute, EXECUTION_ORDER
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.dashboard_export import export_dashboard
from nhl_true_blender_engine.tests.test_engine import snapshot, DATE
from scripts.publish_site_state import export_run
from scripts.verify_published_core import verify_published_core


def fixture(root):
    con=open_db(str(root/"contract.sqlite"))
    try:
        slate=snapshot(2)
        result=execute(con,slate,DATE,"CONFIRMED")
        assert result["card"] is not None, result["errors"]
        result["gateCertification"]=certify_gates(con,DATE,"CONFIRMED",2)
        status=export_run(con,DATE,"CONFIRMED",result,root)
        assert status["currentRunFullyCertified"] is True
        export_dashboard(con,DATE,"CONFIRMED",slate,root)
    finally:
        con.close()
    def read(sub):
        return json.loads((root/sub/f"{DATE}.json").read_text())
    return read("site_runs"),read("site_cards"),read("site_gates")


def persist(root,run,card,gates):
    for sub,record in [("site_runs",run),("site_cards",card),
                       ("site_gates",gates)]:
        (root/sub/f"{DATE}.json").write_text(json.dumps(record))


def test_saved_engine_core_passes_one_original_gate_sequence(tmp_path):
    fixture(tmp_path)
    result=verify_published_core(tmp_path,DATE)
    assert result["status"]=="ORIGINAL_G0_G18_CORE_VERIFIED"
    assert len(result["selected"])==2
    assert all(x["checks"]==len(EXECUTION_ORDER) for x in result["selected"])


@pytest.mark.parametrize("mutate",[
    lambda run,card,g: g["legs"][0]["gateDetails"].pop(11),
    lambda run,card,g: g["legs"][0]["gateDetails"][11].update(
        {"status":"NOT_EXECUTED"}),
    lambda run,card,g: g["legs"][1]["gateDetails"][11].update(
        {"sourceIds":[]}),
    lambda run,card,g: g["legs"][0]["gateDetails"][4]["evidence"][
        "originalFunctionEvidence"][0]["evidence"].update(
            {"masterGateVerdictCopied":True}),
    lambda run,card,g: g["legs"][0]["gateDetails"][-1].update(
        {"evaluatedAt":"2099-01-01T02:00:00Z"}),
    lambda run,card,g: g.update({"fingerprint":"different Core"}),
    lambda run,card,g: g["legs"][0]["gateDetails"][-1]["evidence"][
        "pathClassificationEvidence"].update({"pathQuotaApplied":True}),
    lambda run,card,g: run["gateCertification"]["gateChecksAttempted"].update(
        {"G0":1}),
    lambda run,card,g: run["allG18QualifiedSurvivors"].append(
        {"gameId":"unreviewed-game","playerId":"unreviewed-player"}),
])
def test_rejects_missing_skipped_aliased_or_relabelled_source_proof(tmp_path,mutate):
    run,card,gates=fixture(tmp_path)
    mutate(run,card,gates)
    persist(tmp_path,run,card,gates)
    with pytest.raises(AssertionError,match="BLENDER CORE CONTRACT FAILED"):
        verify_published_core(tmp_path,DATE)


def test_g18_rejects_unreported_extra_survivor(tmp_path):
    run,card,gates=fixture(tmp_path)
    run["allG18QualifiedSurvivors"].append(
        {"gameId":"unreviewed-game","playerId":"unreviewed-player"})
    persist(tmp_path,run,card,gates)
    with pytest.raises(AssertionError,match="silently dropped"):
        verify_published_core(tmp_path,DATE)
