"""G10.5/G16 compare only meaningful challengers.

A teammate ELIMINATED before G10.5 cannot own a route and knock out a
candidate who passed G0-G10. An UNRESOLVED teammate is still compared and
can keep the decision open, but it cannot eliminate anyone.
"""
import json
from nhl_true_blender_engine.engine import execute, stopped_before_g10_5
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import DATE, snapshot
from nhl_true_blender_engine.tests.test_original_recurrence_execution import _mutate_one_off


def _gate(con, pid, gate):
    row=con.execute("""SELECT disposition, details FROM gates WHERE slate_date=?
        AND stage='CONFIRMED' AND player_id=? AND gate=?""",(DATE,pid,gate)).fetchone()
    return row['disposition'], json.loads(row['details'])['evidence']


def test_eliminated_rival_cannot_eliminate_and_is_listed(tmp_path):
    con=open_db(str(tmp_path/'x.sqlite'))
    try:
        s=snapshot(); _mutate_one_off(s)
        execute(con,s,DATE,'CONFIRMED')
        assert _gate(con,'1010','G7')[0]=='ELIMINATED'
        for gate in ('G10.5','G16'):
            disp,ev=_gate(con,'1011',gate)
            assert disp=='PASS', (gate,disp,ev)
            assert ev['challengersStoppedBeforeG10_5']['1010'].endswith(':ELIMINATED')
            assert '1010' in ev['eliminatedChallengersExcluded']
            assert not ev.get('routeOwnedByStrongerRival')
    finally:
        con.close()


def test_stop_map_distinguishes_eliminated_and_unresolved():
    def res(pid, **gates):
        return {'player':{'id':pid},'dispositions':{g:{'disposition':d} for g,d in gates.items()}}
    out=stopped_before_g10_5([
        res('a',G0='PASS',G1='PASS',G2='ELIMINATED'),
        res('b',G0='PASS',G1='NOT_EXECUTED'),
        res('c',**{g:'PASS' for g in ('G0','G1','G2','G3','G4','G5','G6','G7','G8','G9','G10')})])
    assert out=={'a':'G2:ELIMINATED','b':'G1:NOT_EXECUTED'}


def test_unresolved_rival_cannot_eliminate(tmp_path, monkeypatch):
    from nhl_true_blender_engine import engine
    # Every teammate is treated as unresolved before G10.5 and as a
    # dominating same-lane rival. That may keep G10.5/G16 open, never ELIMINATE.
    real_stop=engine.stopped_before_g10_5
    def all_unresolved(results):
        real_stop(results)
        return {str(r['player']['id']):'G6:NOT_EXECUTED' for r in results}
    def dominated(player,rivals,weak,green):
        return False,[{'challengerId':str(r['id']),'status':'RIVAL_DOMINATES',
                       'sameLane':True,'sourceUrls':[]} for r in rivals]
    monkeypatch.setattr(engine,'stopped_before_g10_5',all_unresolved)
    monkeypatch.setattr(engine,'challenger_proof',dominated)
    con=open_db(str(tmp_path/'y.sqlite'))
    try:
        result=engine.execute(con,snapshot(),DATE,'CONFIRMED')
        assert result['card'] is None
        rows=con.execute("""SELECT player_id, disposition, details FROM gates
            WHERE slate_date=? AND stage='CONFIRMED' AND gate IN ('G10.5','G16')""",
            (DATE,)).fetchall()
        assert rows
        for row in rows:
            ev=json.loads(row['details'])['evidence']
            if ev.get('alreadyEliminatedAtGate'):
                continue
            assert row['disposition']!='ELIMINATED', (row['player_id'],ev)
            assert ev['unresolvedChallengersCannotEliminate']
    finally:
        con.close()


def _review(rows, **over):
    c={'unresolved':True,
       'goalieStrengthReview':{'opposingBranchesReviewed':1,'matchedWeakAreas':1,
                               'strongerAreaContradiction':False},
       'lineupDisagreementReview':{'hasProjectedOrConfirmedRole':True},
       'strongestRivalReview':{'everyRivalReviewed':True,'rivalResults':rows}}
    c.update(over)
    return c


def test_g17_ignores_only_eliminated_rivals():
    from nhl_true_blender_engine.rival_scope import g17_resolved_without_eliminated_rivals as f
    rows=[{'challengerId':'9','status':'RIVAL_DOMINATES'},
          {'challengerId':'8','status':'DEFEATED'}]
    assert f(_review(rows),{'9'})=={'resolved':True,'ignoredEliminatedRivals':['9']}
    # A live (not eliminated) dominating rival keeps G17 open.
    assert f(_review(rows),set())['resolved'] is False
    # Every other condition the review checked still applies.
    bad=_review(rows); bad['goalieStrengthReview']['strongerAreaContradiction']=True
    assert f(bad,{'9'})['resolved'] is False
    bad=_review(rows); bad['lineupDisagreementReview']['hasProjectedOrConfirmedRole']=False
    assert f(bad,{'9'})['resolved'] is False
    # Already-resolved or missing reviews are untouched.
    assert f(_review(rows,unresolved=False),{'9'})['resolved'] is False
    assert f(None,{'9'})['resolved'] is False
