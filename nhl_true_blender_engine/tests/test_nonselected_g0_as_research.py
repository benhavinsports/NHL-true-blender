"""A genuinely unresolved G0 matchup must stay visible, not corrupt a
separate three-game Core whose original gate evidence is fully sourced.
Only previously selected games are Core candidates; no fake G0 PASS.
"""
from nhl_true_blender_engine.engine import execute
from nhl_true_blender_engine.storage import open_db
from nhl_true_blender_engine.tests.test_engine import DATE, snapshot


def test_fourth_unresolved_goalie_game_does_not_invalidate_three_actual_survivors(tmp_path):
    s=snapshot(4)
    g=s['games'][3]
    # Source records for both goalies are present, but neither supports
    # a credible weak attack area. No attack direction is invented.
    g['goalies'][g['home']][0]['data']['weakZones']={}
    con=open_db(str(tmp_path/'g0_nonselected.sqlite'))
    try:
        result=execute(con,s,DATE,'CONFIRMED')
        assert result['card'] is not None, result['errors']
        assert len(result['card']['current_legs'])==3
        assert str(g['id']) not in {
            x['gameId'] for x in result['card']['current_legs']}
        assert result['errors']==[]
        assert result['nonselectedGameResearchNotes']
        assert any(str(g['id']) in note and 'G0' in note
                   for note in result['nonselectedGameResearchNotes'])
        # The fourth matchup is researched, not given a fake scorer.
        assert str(g['id']) not in result['g0TwoGoalieDirectionDecisions']
    finally:
        con.close()
