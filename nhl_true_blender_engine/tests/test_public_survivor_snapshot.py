"""The public survivor deck may preserve real prior fully certified pre-puck evidence,
but must never fill any card by a guessed name or promote projected to confirmed.
"""
import copy
import json
from pathlib import Path

from scripts.public_survivor_snapshot import choose_public_survivors, persist_fully_certified_cohort

ROOT=Path(__file__).resolve().parents[2]
DATE="2026-11-17"


def real_files():
    status=json.loads((ROOT/"state/site_runs"/(DATE+".json")).read_text())
    snap=json.loads((ROOT/"state/survivor_cohorts"/(DATE+".json")).read_text())
    return status,snap


def test_incomplete_confirmed_stage_keeps_original_full_verified_projected_pool():
    status,snapshot=real_files()
    status["currentRunFullyCertified"]=False
    status["updatedUTC"]="2026-11-17T22:20:00Z"
    status["gameSurvivorPool"]=[{"gameId":g["gameId"],"matchup":g["matchup"],
                                  "status":"NO_SURVIVOR"} for g in snapshot["gameSurvivorPool"]]
    pool,meta=choose_public_survivors(status,snapshot,DATE)
    assert len(pool)==11
    assert all(g["status"]=="SURVIVOR" for g in pool)
    assert meta["origin"]=="LAST_FULLY_SOURCE_CERTIFIED_PREPUCK_COHORT"
    assert meta["sourceStage"]=="PROJECTED"
    assert meta["newerResearchNotFullyCertified"] is True
    assert [g["survivor"]["playerId"] for g in pool]==[
        g["survivor"]["playerId"] for g in snapshot["gameSurvivorPool"]]


def test_strictly_newer_fully_certified_run_never_replaced_by_older_archive():
    status,snapshot=real_files()
    status["currentRunFullyCertified"]=True
    status["gameSurvivorPool"]=[{"gameId":"test","status":"SURVIVOR","survivor":{"playerId":"1"}}]
    pool,meta=choose_public_survivors(status,snapshot,DATE)
    assert pool is status["gameSurvivorPool"]
    assert meta["origin"]=="CURRENT_ENGINE_RUN"


def test_stale_wrong_date_forged_and_unmatched_snapshot_fails_closed():
    status,snapshot=real_files()
    status["currentRunFullyCertified"]=False
    status["updatedUTC"]="2026-11-17T22:20:00Z"
    for change in (
        {"slateDate":"2026-11-16"},
        {"originalFullRunSourceCertified":False},
        {"certifiedAtUTC":"2099-01-01T00:00:00Z"},
        {"sourceGitCommit":"not-a-commit"},
        {"certifiedGameCount":10},
        {"originalPublicationDecision":"NO_VERIFIED_CORE"},
    ):
        changed={**snapshot,**change}
        pool,meta=choose_public_survivors(status,changed,DATE)
        assert pool is status["gameSurvivorPool"]
        assert meta["origin"]=="CURRENT_ENGINE_RUN"
    changed=copy.deepcopy(snapshot)
    changed["gameSurvivorPool"][0]["survivor"]["playerId"]=""
    assert choose_public_survivors(status,changed,DATE)[1]["origin"]=="CURRENT_ENGINE_RUN"
    changed=copy.deepcopy(snapshot)
    changed["gameSurvivorPool"][0]["gameStartUTC"]="2026-11-17T21:00:00Z"
    assert choose_public_survivors(status,changed,DATE)[1]["origin"]=="CURRENT_ENGINE_RUN"


def test_writer_requires_full_run_card_exact_all_game_survivors_and_prepuck(tmp_path):
    status,snapshot=real_files()
    result={"games":11,"gameSurvivorPool":snapshot["gameSurvivorPool"],
            "card":{"cardId":"fixture"},
            "gateCertification":{"selectedCoreOnlyFullyCertified":True}}
    sha="a"*40
    assert persist_fully_certified_cohort(tmp_path,DATE,"PROJECTED",result,sha,"test-fixture")
    saved=json.loads((tmp_path/"survivor_cohorts"/(DATE+".json")).read_text())
    assert len(saved["gameSurvivorPool"])==11
    assert saved["originalFullRunSourceCertified"] is True
    assert saved["sourceWorkflowRunId"]=="test-fixture"
    bad=copy.deepcopy(result)
    bad["gameSurvivorPool"][0]["status"]="NO_SURVIVOR"
    assert not persist_fully_certified_cohort(tmp_path,DATE,"CONFIRMED",bad,sha)
    assert json.loads((tmp_path/"survivor_cohorts"/(DATE+".json")).read_text())==saved
