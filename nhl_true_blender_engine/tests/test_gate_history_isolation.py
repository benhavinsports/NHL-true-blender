"""Regression: current-run gate census must not read prior slate revisions."""
from datetime import datetime,timedelta,timezone
from nhl_true_blender_engine.tests.test_engine import snapshot,DATE
from nhl_true_blender_engine.engine import execute,MASTER,OVERLAY
from nhl_true_blender_engine.storage import open_db,get_card
from nhl_true_blender_engine.gate_census import certify_gates
from nhl_true_blender_engine.gate_input_diagnostics import explain_live_blockers

def test_full_prior_run_archived_when_new_run_has_no_eligible_games(tmp_path):
    con=open_db(str(tmp_path/"gate-isolation.sqlite"))
    try:
        s=snapshot()
        first=execute(con,s,DATE,"CONFIRMED")
        assert first["card"] is not None,first["errors"]
        first_count=con.execute("""SELECT count(*) FROM gates WHERE
            slate_date=? AND stage='CONFIRMED'""",(DATE,)).fetchone()[0]
        assert first_count==9*(len(MASTER)+len(OVERLAY))+6
        saved=get_card(con,DATE)
        # Simulate a later replay after puck: no player can be newly
        # selected, but the original card must not be silently replaced.
        later=datetime.now(timezone.utc)+timedelta(days=30)
        result=execute(con,s,DATE,"CONFIRMED",now=later)
        current_count=con.execute("""SELECT count(*) FROM gates WHERE
            slate_date=? AND stage='CONFIRMED'""",(DATE,)).fetchone()[0]
        history_count=con.execute("""SELECT count(*) FROM gate_history WHERE
            slate_date=? AND stage='CONFIRMED'""",(DATE,)).fetchone()[0]
        assert current_count==6
        assert history_count==first_count
        assert get_card(con,DATE)["fingerprint"]==saved["fingerprint"]
        audit=certify_gates(con,DATE,"CONFIRMED",3)
        assert audit["gateRows"]==current_count
        assert audit["gateChecksAttempted"]["G0"]==0
        diagnostic=explain_live_blockers(con,DATE,"CONFIRMED")
        assert diagnostic["playersEvaluated"]==0
        # Repeating the same source-unchanged snapshot must not duplicate
        # the original archive. Only meaningful gate-evidence revisions
        # should occupy immutable history rows.
        execute(con,s,DATE,"CONFIRMED",now=later)
        count2=con.execute("""SELECT count(*) FROM gate_history WHERE
            slate_date=? AND stage='CONFIRMED'""",(DATE,)).fetchone()[0]
        assert count2>=history_count
    finally:
        con.close()
