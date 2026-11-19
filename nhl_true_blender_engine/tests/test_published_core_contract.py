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
    lambda run,card,g: run["preCoreQualifiedSurvivors"].append(
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
    run["preCoreQualifiedSurvivors"].append(
        {"gameId":"unreviewed-game","playerId":"unreviewed-player"})
    persist(tmp_path,run,card,gates)
    with pytest.raises(AssertionError,match="silently dropped"):
        verify_published_core(tmp_path,DATE)



def test_run_receipt_distinguishes_final_core_nonselection_from_missing_sources(tmp_path):
    run, card, gates=fixture(tmp_path)
    dispositions=run["gateCertification"]["masterGateDispositions"]["G18"]
    nonselected=run["g18IntentionallyNotSelectedNotMissingSource"]
    assert dispositions["PASS"]==2
    assert nonselected==dispositions["NOT_EXECUTED"]
    assert nonselected>0
    assert run["missingByGate"].get("G18",0)==0
    assert run["currentRunFullyCertified"] is True


def test_new_saved_receipt_uses_only_pre_core_key(tmp_path):
    run, card, gates = fixture(tmp_path)
    assert "preCoreQualifiedSurvivors" in run
    assert "allG18QualifiedSurvivors" not in run
    assert len(run["preCoreQualifiedSurvivors"]) == 2
    assert verify_published_core(tmp_path, DATE)["status"] == "ORIGINAL_G0_G18_CORE_VERIFIED"


def test_legacy_saved_receipt_remains_readable_without_rewriting_it(tmp_path):
    run, card, gates = fixture(tmp_path)
    original = run.pop("preCoreQualifiedSurvivors")
    run["allG18QualifiedSurvivors"] = original  # Intentional historical read-only fixture.
    persist(tmp_path, run, card, gates)
    assert verify_published_core(tmp_path, DATE)["status"] == "ORIGINAL_G0_G18_CORE_VERIFIED"
    assert "preCoreQualifiedSurvivors" not in run


def test_new_key_takes_precedence_over_legacy_fallback():
    from nhl_true_blender_engine.core_identity import pre_core_survivors
    current = [{"gameId": "1", "playerId": "A"}]
    stale = [{"gameId": "2", "playerId": "B"}]
    assert pre_core_survivors({
        "preCoreQualifiedSurvivors": current,
        "allG18QualifiedSurvivors": stale,
    }) is current


def test_public_survivor_cards_show_actual_g6_g8_g12_evidence(tmp_path):
    run, _, _ = fixture(tmp_path)
    receipts = run["gameSurvivorGateReceipts"]
    assert receipts
    for rows in receipts.values():
        gates = {item["gate"]: item for item in rows}
        g6 = gates["G6"]["evidence"]
        g8 = gates["G8"]["evidence"]
        g12 = gates["G12"]["evidence"]
        assert g6["deployment"]["EV"]
        assert "projectedNotPromoted" in g6
        assert g8["neutralWhenAbsent"] is True
        assert g8["neverRankingShortcut"] is True
        assert g12["officialGoalsReconciled"] is True
        assert g12["ownership"]["creditedGoalsVerified"] is True


def test_unresolved_refresh_keeps_older_verified_frozen_core_visible_but_uncertified(tmp_path):
    from scripts.publish_site_state import export_run
    from nhl_true_blender_engine.storage import open_db
    run, card, _ = fixture(tmp_path)
    original = (tmp_path/"site_cards"/f"{DATE}.json").read_bytes()
    con=open_db(str(tmp_path/"contract.sqlite"))
    try:
        later = export_run(con,DATE,"CONFIRMED",{
            "card":None,"games":2,"gateCertification":run["gateCertification"],
            "errors":["PRE_CORE_REVIEW: certified opponents now unresolved"],
            "preCoreQualifiedSurvivors":[]},tmp_path)
    finally:
        con.close()
    assert later["publicationDecision"]=="G18_UPSTREAM_SURVIVORS_UNRESOLVED"
    assert later["retainedOriginalLockedCard"] is True
    assert later["historicalCardIsNotCurrentRunCertification"] is True
    assert later["currentRunFullyCertified"] is False
    assert later["publishedToSite"] is True
    assert later["cardId"]==card["cardId"]
    assert (tmp_path/"site_cards"/f"{DATE}.json").read_bytes()==original
    with pytest.raises(AssertionError,match="BLENDER CORE CONTRACT FAILED"):
        verify_published_core(tmp_path, DATE)


def test_incomplete_gate_recheck_keeps_original_verified_card_without_new_pass(tmp_path):
    from scripts.publish_site_state import export_run
    from nhl_true_blender_engine.storage import open_db
    run, card, _ = fixture(tmp_path)
    con=open_db(str(tmp_path/"contract.sqlite"))
    try:
        later=export_run(con,DATE,"CONFIRMED",{
            "card":None,"games":2,
            "gateCertification":{"scannedSkaters":0},
            "errors":["SOURCE_INCOMPLETE"]},tmp_path)
    finally:
        con.close()
    assert later["publicationDecision"]=="FULL_GATE_EXECUTION_INCOMPLETE"
    assert later["retainedOriginalLockedCard"] is True
    assert later["historicalCardIsNotCurrentRunCertification"] is True
    assert later["publishedToSite"] is True
    assert later["currentRunFullyCertified"] is False
    assert json.loads((tmp_path/"site_cards"/f"{DATE}.json").read_text())==card
