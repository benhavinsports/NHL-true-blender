"""No executed candidate pool cannot be advertised as every gate evidenced."""
import pytest
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE


@pytest.mark.parametrize('with_schedule',[False,True])
def test_empty_candidate_pool_never_claims_all_gate_evidence(with_schedule):
    con=open_db(':memory:')
    try:
        if with_schedule:
            s=snapshot()
            for game in s['games']:
                game['goalies']={}
            execute(con,s,DATE,'CONFIRMED')
        audit=certify_gates(con,DATE,'CONFIRMED',3)
        assert audit['scannedSkaters']==0
        assert audit['allGateChecksExecutedWithEvidence'] is False
        assert audit['allOverlayStepsSourceCompleteForEveryRejectedSkater'] is False
        assert audit['fullIndependentCardCertification'] is False
    finally:
        con.close()


def test_missing_record_is_not_equivalent_to_no_unexecuted_records():
    con=open_db(':memory:')
    try:
        execute(con,snapshot(),DATE,'CONFIRMED')
        con.execute("DELETE FROM gates WHERE gate='G1'")
        con.commit()
        audit=certify_gates(con,DATE,'CONFIRMED',3)
        assert audit['missingMatrixGateRows']['G1']>0
        assert audit['allGateChecksExecutedWithEvidence'] is False
    finally:
        con.close()
