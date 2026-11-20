"""An empty input must remain a source error and be reportable by the CLI."""
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.storage import open_db, get_card


def test_empty_schedule_retains_report_contract_without_claiming_core():
    con = open_db(':memory:')
    try:
        result = execute(con, {'games': []}, '2026-11-20')
        # These fields are consumed by run_true_blender after persistence.
        for field in ('games', 'eligibleSkaterRows', 'gateRows',
                      'g0Complete', 'g0Directions'):
            assert result[field] == 0
        assert result['missingByGate'] == {}
        assert result['card'] is None
        assert result['errors'] == ['No official NHL game data provided']
        assert get_card(con, '2026-11-20') is None
    finally:
        con.close()
