"""Regression tests for gate-matrix certification and publication integrity."""
import json
from gate_executor import ORDER, eliminate_player, execute_gate_matrix
from core_publication import publish_verified_core

def trace(statuses=None):
    statuses = statuses or {}
    return [{"gate": g, "status": statuses.get(g, "PASS"), "evidence": ["fixture"]} for g in ORDER]

def player(pid, game, statuses=None):
    return {"playerId": pid, "player": str(pid), "team": "TEST", "gateTrace": trace(statuses)}

def test_gate_order_contains_10_5_once():
    assert len(ORDER) == 20
    assert ORDER[11] == "G10.5"
    assert len(set(ORDER)) == len(ORDER)

def test_elimination_records_first_failure_without_fake_later_passes():
    p = eliminate_player({**player(1, 1, {"G5": "ELIMINATED"}), "gameId": 1})
    assert p["eliminated"] and not p["survived"]
    assert p["firstFailureGate"] == "G5"
    assert all(d["decision"] == "SKIPPED_AFTER_ELIMINATION" for d in p["decisions"][6:])

def test_missing_evidence_never_certifies():
    p = eliminate_player({**player(1, 1, {"G6": "UNRESOLVED"}), "gameId": 1})
    assert not p["survived"] and not p["eliminated"] and not p["complete"]

def test_full_pool_counts_eliminations_separately_from_unresolved():
    report = {"games": [{"game": {"gameId": 1}, "players": [
        player(1, 1, {"G5": "ELIMINATED"}),
        player(2, 1, {"G6": "UNRESOLVED"}),
        player(3, 1),
    ]}]}
    result = execute_gate_matrix(report)
    assert result["playersEvaluated"] == 3
    assert result["playersEliminated"] == 1
    assert result["playersWithMissingEvidence"] == 1
    assert result["playersFullySurvived"] == 1

def test_no_unverified_card_is_published(tmp_path):
    report = {"slateDate": "2026-11-15", "validationSummary": {"finalPlayerPathsCertified": False},
              "coreOutput": {"core": [player(1, 1)]}, "gameCount": 3}
    result = publish_verified_core(report, str(tmp_path))
    assert result["published"] is False
    assert not list(tmp_path.iterdir())

def test_single_card_immutable_without_replacement_audit(tmp_path):
    def report(ids):
        return {"slateDate": "2026-11-15", "mode": "projected",
                "runId": "test", "gameCount": 3,
                "validationSummary": {"finalPlayerPathsCertified": True},
                "coreOutput": {"core": [
                    {**player(pid, gid), "gameId": gid} for gid, pid in enumerate(ids, 1)
                ], "status": "VERIFIED"}}
    assert publish_verified_core(report([11, 22, 33]), str(tmp_path))["published"]
    assert not publish_verified_core(report([11, 22, 33]), str(tmp_path))["published"]
    assert not publish_verified_core(report([11, 44, 33]), str(tmp_path))["published"]
    saved = json.loads((tmp_path / "authoritative_core_2026-11-15.json").read_text())
    assert [x["playerId"] for x in saved["core"]] == [11, 22, 33]
