"""Explicitly authorized one-slate retirement of an invalid old G18 Core."""
import json
from pathlib import Path

import pytest

from nhl_true_blender_engine.storage import open_db
from scripts.retract_invalid_core import (
    CARD_ID, DATE, ORIGINAL_FINGERPRINT, REASON, retract,
)


def fixture(root: Path):
    for directory in ("site_cards", "site_runs", "core_retractions"):
        (root/directory).mkdir(parents=True, exist_ok=True)
    ledger = open_db(str(root / "true_blender.sqlite"))
    original_legs = [
        {"gameId":str(i),"playerId":str(i*10),
         "player":"Fixture skater","path":"PRIMARY",
         "sourceIds":["https://api-web.nhle.com/v1/"],
         "startUTC":"2026-11-18T00:00:00Z"}
        for i in range(1,4)]
    ledger.execute(
        "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?)",
        (DATE,CARD_ID,json.dumps(original_legs),json.dumps(original_legs),
         "PROJECTED",ORIGINAL_FINGERPRINT,1,"2026-11-17T12:00:00Z",
         "2026-11-17T12:00:00Z",None))
    ledger.execute(
        "INSERT INTO card_versions VALUES (?,?,?,?,?,?,?,?,?)",
        (CARD_ID+"-v1",DATE,CARD_ID,1,"PROJECTED",ORIGINAL_FINGERPRINT,
         json.dumps(original_legs),json.dumps({"type":"FIRST_ISSUANCE"}),
         "2026-11-17T12:00:00Z"))
    ledger.execute(
        "INSERT INTO gates VALUES (?,?,?,?,?,?,?,?)",
        (DATE,"PROJECTED","1","10","G0","PASS",
         json.dumps({"sourceIds":["https://api-web.nhle.com/v1"]}),
         "2026-11-17T12:00:00Z"))
    ledger.close()
    survivors=[
        {"gameId":str(i),"playerId":str(i*10)}
        for i in range(1,5)]
    (root/"site_cards"/f"{DATE}.json").write_text(json.dumps({
        "cardId":CARD_ID,"fingerprint":ORIGINAL_FINGERPRINT,
        "verified":False,"status":"RETRACTED_UNAUTHORIZED_G18"}))
    (root/"site_runs"/f"{DATE}.json").write_text(json.dumps({
        "slateDate":DATE,"errors":["PRE_CORE_REVIEW: four upstream survivors"],
        "preCoreQualifiedSurvivors":survivors}))
    (root/"core_retractions"/f"{DATE}.json").write_text(json.dumps({
        "slateDate":DATE,"cardId":CARD_ID,
        "originalFingerprint":ORIGINAL_FINGERPRINT,
        "reason":REASON,
        "approval":"USER_EXPLICITLY_REJECTED_OLD_G18_CARD",
        "upstreamSurvivors":survivors}))


def test_withdraws_only_discredited_selected_card_and_preserves_full_original(tmp_path):
    fixture(tmp_path)
    first=retract(tmp_path)
    assert first["status"]=="ORIGINAL_RETRACTED_FROM_ACTIVE_LEDGER"
    assert first["originalVersionsPreserved"]==1
    # Fresh evidence is expected to change after the corrected engine runs.
    # Old first-retraction proof is immutable and must not be required again.
    run_path=tmp_path/"site_runs"/f"{DATE}.json"
    run_path.write_text(json.dumps({
        "slateDate":DATE,"errors":[],"preCoreQualifiedSurvivors":[]}))
    assert retract(tmp_path)["status"]=="ORIGINAL_ALREADY_RETRACTED"
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]==0
    assert con.execute("SELECT COUNT(*) FROM card_versions").fetchone()[0]==0
    saved=con.execute("SELECT * FROM card_retractions WHERE slate_date=?",(DATE,)).fetchone()
    assert saved is not None and saved["original_fingerprint"]==ORIGINAL_FINGERPRINT
    assert len(json.loads(saved["original_versions"]))==1
    assert json.loads(saved["original_card"])["fingerprint"]==ORIGINAL_FINGERPRINT
    # No gate data or historical receipts are changed by a status correction.
    assert con.execute("SELECT COUNT(*) FROM gates WHERE slate_date=?",(DATE,)).fetchone()[0]==1
    con.close()


def test_will_not_retract_when_four_survivor_proof_disagrees(tmp_path):
    fixture(tmp_path)
    path=tmp_path/"site_runs"/f"{DATE}.json"
    bad=json.loads(path.read_text())
    bad["preCoreQualifiedSurvivors"].pop()
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match="four-survivor"):
        retract(tmp_path)
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]==1
    con.close()


def test_will_not_retract_different_card_or_officially_graded_slate(tmp_path):
    fixture(tmp_path)
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    con.execute("UPDATE cards SET grade=? WHERE slate_date=?",
                (json.dumps({"result":"LOSS"}),DATE))
    con.close()
    with pytest.raises(ValueError,match="officially graded"):
        retract(tmp_path)
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]==1
    con.close()


def test_new_independent_card_can_be_issued_after_retraction(tmp_path):
    from datetime import datetime, timezone
    from nhl_true_blender_engine.storage import save_card, get_card
    fixture(tmp_path)
    assert retract(tmp_path)["status"]=="ORIGINAL_RETRACTED_FROM_ACTIVE_LEDGER"
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    fresh=[{"gameId":str(i),"playerId":str(100+i),
            "player":f"Actual fresh engine survivor {i}","path":"PRIMARY",
            "sourceIds":["https://api-web.nhle.com/v1/"],
            "startUTC":"2026-11-18T00:00:00Z",
            "gameState":"FUT"}
           for i in range(1,4)]
    new=save_card(con,DATE,"PROJECTED",fresh,11,
                  now=datetime(2026,11,17,12,tzinfo=timezone.utc))
    assert new["fingerprint"]!=ORIGINAL_FINGERPRINT
    assert new["revision"]==1
    assert get_card(con,DATE)["current_legs"]==fresh
    con.commit()
    assert retract(tmp_path)["status"]=="NEW_CORRECTED_CARD_EXISTS"
    # Retraction is a historical audit, not a second authoritative card.
    assert con.execute("SELECT COUNT(*) FROM card_retractions").fetchone()[0]==1
    assert con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]==1
    con.close()


def test_reissue_of_same_player_fingerprint_after_retraction_is_not_old_card(tmp_path):
    """No forcing three different names merely to look like a replacement."""
    from datetime import datetime,timedelta
    fixture(tmp_path)
    retract(tmp_path)
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    row=con.execute("SELECT * FROM card_retractions WHERE slate_date=?",(DATE,)).fetchone()
    old=json.loads(row["original_card"])
    issued=(datetime.fromisoformat(row["retracted_at_utc"])+
            timedelta(seconds=2)).isoformat()
    old["first_issued_at"]=issued
    old["updated_at"]=issued
    con.execute("""INSERT INTO cards
        (slate_date,card_id,initial_legs,current_legs,stage,fingerprint,
         revision,first_issued_at,updated_at,grade)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        tuple(old[k] for k in (
            "slate_date","card_id","initial_legs","current_legs","stage",
            "fingerprint","revision","first_issued_at","updated_at","grade")))
    con.execute("""INSERT INTO card_versions VALUES (?,?,?,?,?,?,?,?,?)""",
        (CARD_ID+"-v1",DATE,CARD_ID,1,"PROJECTED",ORIGINAL_FINGERPRINT,
         old["current_legs"],json.dumps({"type":"FIRST_ISSUANCE"}),issued))
    con.close()
    result=retract(tmp_path)
    assert result["status"]=="NEW_CORRECTED_CARD_EXISTS"
    assert result["identicalPlayersMayBeIndependentlyReissued"] is True


def test_original_timestamp_cannot_reenter_after_retraction(tmp_path):
    fixture(tmp_path)
    retract(tmp_path)
    con=open_db(str(tmp_path/"true_blender.sqlite"))
    row=con.execute("SELECT * FROM card_retractions WHERE slate_date=?",(DATE,)).fetchone()
    old=json.loads(row["original_card"])
    con.execute("""INSERT INTO cards
        (slate_date,card_id,initial_legs,current_legs,stage,fingerprint,
         revision,first_issued_at,updated_at,grade)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        tuple(old[k] for k in (
            "slate_date","card_id","initial_legs","current_legs","stage",
            "fingerprint","revision","first_issued_at","updated_at","grade")))
    con.close()
    with pytest.raises(ValueError,match="Retracted original returned"):
        retract(tmp_path)
