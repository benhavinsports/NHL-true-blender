"""Original G7/G11 and Step4/Step9: repeat dated evidence, not checklist PASS.

These are synthetic fixtures; they never choose or replace a real scorer.
November 17 exposed zero goal dates and [0,0,3] shots as a false PASS.
"""
import json
from nhl_true_blender_engine.engine import execute, EXECUTION_ORDER
from nhl_true_blender_engine.route_continuation import (
    observed_own_shot_appearances, observed_dated_recurrence)
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import DATE, snapshot


def _evidence(con, pid):
    outcomes={}
    for row in con.execute(
        """SELECT gate, disposition, details FROM gates
           WHERE slate_date=? AND stage='CONFIRMED' AND player_id=?""",
        (DATE, pid)).fetchall():
        outcomes[row['gate']]=row['disposition']
        for fn in (json.loads(row['details'])['evidence']
                   .get('originalFunctionEvidence') or []):
            outcomes[fn['step']]=fn['disposition']
    return outcomes


def _mutate_one_off(s):
    first=s['games'][0]['rosters']['T1A']['data']['players'][0]
    first['mappedGoals']['data']['goals']=[]
    first['officialGoalTotal']['data']['goals']=0
    first['pressure']['data']['recentAppearanceShots']=[0,0,3]
    first['pressure']['data']['appearances']=[
        {'date':'2026-11-01'},{'date':'2026-11-02'},
        {'date':'2026-11-03'}]


def test_isolated_one_game_shot_and_no_recent_goals_does_not_pass_recurrence(tmp_path):
    con=open_db(str(tmp_path/'one_off.sqlite'))
    try:
        sample=snapshot()
        _mutate_one_off(sample)
        result=execute(con,sample,DATE,'CONFIRMED')
        rows=_evidence(con,'1010')
        # Actual dated source contradictions eliminate the scorer; G18
        # records the earlier failure without inventing a fourth pick.
        for gate in ('G7','G11','Step4','Step9'):
            assert rows[gate]=='ELIMINATED', (gate,rows[gate])
        assert rows['G18']=='NOT_EXECUTED'
        assert set(EXECUTION_ORDER).issubset(rows)
        assert result['card'] is None
    finally:
        con.close()


def test_dated_shots_can_prove_recurrence_even_with_zero_goals():
    shots=observed_own_shot_appearances({
        'recentAppearanceShots':[2,0,1],
        'appearances':[{'date':'2026-11-12'},{'date':'2026-11-10'},
                       {'date':'2026-11-08'}],
    })
    recurrence=observed_dated_recurrence({
        'appearanceDates':3,'distinctGoalDates':0},shots)
    assert shots['positiveShotAppearances']==2
    assert shots['positiveDatedShotAppearances']==2
    assert recurrence['datedGoalRecurrence'] is False
    assert recurrence['datedOwnShotRecurrence'] is True
    assert recurrence['datedScoringOrShotRecurrence'] is True


def test_zero_date_alignment_does_not_fake_dated_scoring_recurrence():
    shots=observed_own_shot_appearances({
        'recentAppearanceShots':[2,0,1]})
    recurrence=observed_dated_recurrence({
        'appearanceDates':3,'distinctGoalDates':0},shots)
    assert shots['repeatedOwnShotPressure'] is True
    assert recurrence['datedOwnShotRecurrence'] is False
    assert recurrence['datedScoringOrShotRecurrence'] is False


def test_g11_and_step9_can_pass_genuinely_repeated_own_onnet_pressure(tmp_path):
    con=open_db(str(tmp_path/'positive.sqlite'))
    try:
        result=execute(con,snapshot(),DATE,'CONFIRMED')
        rows=_evidence(con,'1010')
        assert result['card'] is not None
        for gate in ('G7','G11','Step4','Step9','G18'):
            assert rows[gate]=='PASS', (gate,rows[gate])
    finally:
        con.close()
